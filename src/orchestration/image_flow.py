from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from src.agents.image_post.schemas import GroupSpec, ImageResult, ResearchResult, XHSContent
from src.config.settings import ImageConfig

from .schemas import (
    DeliveryPackage,
    GroupingItem,
    GroupingResult,
    ImageTaskPlan,
    ReferenceImagePlan,
    ResultEnvelope,
    WorkflowInvocation,
)
from .workflow_graph import ModuleGraphSpec, ModuleNodeSpec


ResearchRunner = Callable[..., Awaitable[ResultEnvelope[ResearchResult]]]
GroupingRunner = Callable[..., Awaitable[ResultEnvelope[GroupingResult]]]
ContentRunner = Callable[..., Awaitable[ResultEnvelope[XHSContent]]]
ImageGroupRunner = Callable[..., Awaitable[ResultEnvelope[ImageResult]]]
DeliveryRunner = Callable[..., Awaitable[ResultEnvelope[DeliveryPackage]]]


@dataclass
class ImageWorkflowDeps:
    run_research: ResearchRunner
    run_grouping: GroupingRunner
    run_content: ContentRunner
    run_image_group: ImageGroupRunner
    run_delivery: DeliveryRunner


@dataclass
class ImageWorkflowState:
    topic: str
    audience: str
    run_id: str
    workspace_dir: Path
    execution_text: str = ""
    invocation: WorkflowInvocation | None = None
    image_count: int | None = None
    single_item_per_image: bool = False
    max_auto_images: int | None = ImageConfig.MAX_AUTO_IMAGES
    image_generation_concurrency: int = 3
    image_task_max_retries: int = 1
    research: ResultEnvelope[ResearchResult] | None = None
    groups: ResultEnvelope[GroupingResult] | None = None
    content: ResultEnvelope[XHSContent] | None = None
    reference_analysis: list[ReferenceImagePlan] = field(default_factory=list)
    image_plan: ImageTaskPlan | None = None
    images: list[ResultEnvelope[ImageResult]] = field(default_factory=list)
    image_set_review_summary: str = ""
    delivery: ResultEnvelope[DeliveryPackage] | None = None
    executed_nodes: list[str] = field(default_factory=list)


@dataclass
class ResearchNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "GroupingNode":
        ctx.state.executed_nodes.append("research")
        result = await ctx.deps.run_research(
            topic=ctx.state.topic,
            audience=ctx.state.audience,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.research = result
        return GroupingNode(research=result)


@dataclass
class GroupingNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ContentNode":
        ctx.state.executed_nodes.append("grouping")
        result = await ctx.deps.run_grouping(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.groups = result
        return ContentNode(research=self.research, groups=result)


@dataclass
class ContentNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ReferenceAnalysisNode":
        ctx.state.executed_nodes.append("content")
        result = await ctx.deps.run_content(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            groups=self.groups,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.content = result
        return ReferenceAnalysisNode(research=self.research, groups=self.groups, content=result)


@dataclass
class ReferenceAnalysisNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImagePlannerNode":
        ctx.state.executed_nodes.append("reference_analysis")
        invocation = ctx.state.invocation or WorkflowInvocation(
            objective=ctx.state.execution_text or ctx.state.topic,
            route="image_post",
            topic=ctx.state.topic,
            audience=ctx.state.audience,
        )
        references = ImageTaskPlan.reference_plans_from_invocation(invocation)
        ctx.state.reference_analysis = references
        return ImagePlannerNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            reference_analysis=references,
        )


@dataclass
class ImagePlannerNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]
    reference_analysis: list[ReferenceImagePlan] = field(default_factory=list)

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImagesNode":
        ctx.state.executed_nodes.append("image_planner")
        invocation = ctx.state.invocation or WorkflowInvocation(
            objective=ctx.state.execution_text or ctx.state.topic,
            route="image_post",
            topic=ctx.state.topic,
            audience=ctx.state.audience,
        )
        image_plan = ImageTaskPlan.plan_from_groups(
            invocation=invocation,
            groups=self.groups.payload or GroupingResult(),
            requested_image_count=ctx.state.image_count,
            single_item_per_image=ctx.state.single_item_per_image,
            max_auto_images=ctx.state.max_auto_images,
            reference_analysis=self.reference_analysis,
        )
        ctx.state.image_plan = image_plan
        return ImagesNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            image_plan=image_plan,
        )


@dataclass
class ImageTaskSubgraphState:
    """Execution trace for one image task subgraph run."""

    executed_nodes: list[str] = field(default_factory=list)
    attempt: int = 0
    last_result: ResultEnvelope[ImageResult] | None = None


@dataclass
class ImagePromptNode:
    """Builds the generation call payload for one planned image task."""

    def run(
        self,
        *,
        subgraph_state: ImageTaskSubgraphState,
        workflow_state: ImageWorkflowState,
        research: ResultEnvelope[ResearchResult],
        content: ResultEnvelope[XHSContent],
        image_task: object,
        index: int,
        image_runner: ImageGroupRunner,
    ) -> dict[str, object]:
        subgraph_state.executed_nodes.append("prompt")
        params: dict[str, object] = {
            "topic": workflow_state.topic,
            "execution_text": workflow_state.execution_text or workflow_state.topic,
            "group": image_task.to_group_payload(),
            "group_index": index,
            "research": research,
            "content": content,
            "run_id": workflow_state.run_id,
            "workspace_dir": workflow_state.workspace_dir,
        }
        if _callable_accepts_param(image_runner, "image_task"):
            params["image_task"] = image_task
        return params


@dataclass
class ImageGenerationNode:
    """Calls the image generation specialist for one planned image task."""

    async def run(
        self,
        *,
        subgraph_state: ImageTaskSubgraphState,
        image_runner: ImageGroupRunner,
        params: dict[str, object],
    ) -> ResultEnvelope[ImageResult]:
        subgraph_state.executed_nodes.append("image_generation")
        result = await image_runner(**params)
        subgraph_state.last_result = result
        return result


@dataclass
class ImageReviewNode:
    """Reviews the image task result envelope before join."""

    def run(
        self,
        *,
        subgraph_state: ImageTaskSubgraphState,
        result: ResultEnvelope[ImageResult],
    ) -> bool:
        subgraph_state.executed_nodes.append("image_review")
        if result.status != "success" or result.payload is None:
            return False
        return bool(result.payload.images)


@dataclass
class ImageRepairRetryNode:
    """Records a repair/retry transition after image review rejection."""

    def run(
        self,
        *,
        subgraph_state: ImageTaskSubgraphState,
    ) -> None:
        subgraph_state.executed_nodes.append("repair_retry")


@dataclass
class ImageTaskSubgraph:
    """Executable prompt -> generation -> review -> retry boundary for one image."""

    deps: ImageWorkflowDeps
    last_state: ImageTaskSubgraphState | None = None

    async def run(
        self,
        *,
        state: ImageWorkflowState,
        research: ResultEnvelope[ResearchResult],
        content: ResultEnvelope[XHSContent],
        image_task: object,
        index: int,
    ) -> ResultEnvelope[ImageResult]:
        subgraph_state = ImageTaskSubgraphState()
        self.last_state = subgraph_state
        prompt_node = ImagePromptNode()
        generation_node = ImageGenerationNode()
        review_node = ImageReviewNode()
        repair_retry_node = ImageRepairRetryNode()
        max_retries = max(0, state.image_task_max_retries)
        last_result: ResultEnvelope[ImageResult] | None = None

        for attempt in range(max_retries + 1):
            subgraph_state.attempt = attempt + 1
            params = prompt_node.run(
                subgraph_state=subgraph_state,
                workflow_state=state,
                research=research,
                content=content,
                image_task=image_task,
                index=index,
                image_runner=self.deps.run_image_group,
            )
            result = await generation_node.run(
                subgraph_state=subgraph_state,
                image_runner=self.deps.run_image_group,
                params=params,
            )
            last_result = result
            if review_node.run(subgraph_state=subgraph_state, result=result):
                return result
            if attempt < max_retries:
                repair_retry_node.run(subgraph_state=subgraph_state)

        if last_result is not None:
            return last_result
        return ResultEnvelope[ImageResult].error(
            agent_name="image_task_subgraph",
            summary="image task did not produce a result",
            error_message="image task did not produce a result",
            run_id=state.run_id,
            step_id=f"image-{index}",
        )


@dataclass
class ImagesNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]
    image_plan: ImageTaskPlan

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImageJoinNode":
        ctx.state.executed_nodes.append("image_task_subgraph")
        concurrency = max(1, ctx.state.image_generation_concurrency)
        semaphore = asyncio.Semaphore(concurrency)
        image_task_subgraph = ImageTaskSubgraph(deps=ctx.deps)

        async def run_limited_image_group(index: int, image_task) -> ResultEnvelope[ImageResult]:
            async with semaphore:
                return await image_task_subgraph.run(
                    state=ctx.state,
                    research=self.research,
                    content=self.content,
                    image_task=image_task,
                    index=index,
                )

        images = await asyncio.gather(
            *[run_limited_image_group(index, image_task) for index, image_task in enumerate(self.image_plan.tasks)]
        )
        ctx.state.images = list(images)
        return ImageJoinNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            images=list(images),
        )


@dataclass
class ImageJoinNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]
    images: list[ResultEnvelope[ImageResult]]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImageSetReviewNode":
        ctx.state.executed_nodes.append("image_join")
        ctx.state.images = list(self.images)
        return ImageSetReviewNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            images=list(self.images),
        )


@dataclass
class ImageSetReviewNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]
    images: list[ResultEnvelope[ImageResult]]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "DeliveryNode":
        ctx.state.executed_nodes.append("image_set_review")
        success_count = sum(
            1
            for image in self.images
            if image.status == "success" and image.payload is not None and bool(image.payload.images)
        )
        ctx.state.image_set_review_summary = f"{success_count}/{len(self.images)} image tasks passed set review"
        return DeliveryNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            images=list(self.images),
        )


@dataclass
class DeliveryNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps, ResultEnvelope[DeliveryPackage]]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]
    images: list[ResultEnvelope[ImageResult]]

    async def run(
        self,
        ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps],
    ) -> End[ResultEnvelope[DeliveryPackage]]:
        ctx.state.executed_nodes.append("delivery")
        result = await ctx.deps.run_delivery(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            groups=self.groups,
            content=self.content,
            images=self.images,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        if result.payload is not None:
            result.payload.metadata.setdefault("workflow_runner", "ImageWorkflowRunner")
            result.payload.metadata["workflow_node_trace"] = list(ctx.state.executed_nodes)
            result.payload.metadata["reference_analysis"] = [
                reference.model_dump(mode="json") for reference in ctx.state.reference_analysis
            ]
            result.payload.metadata["image_set_review"] = ctx.state.image_set_review_summary
        ctx.state.delivery = result
        return End(result)


image_workflow_graph = Graph(
    nodes=(
        ResearchNode,
        GroupingNode,
        ContentNode,
        ReferenceAnalysisNode,
        ImagePlannerNode,
        ImagesNode,
        ImageJoinNode,
        ImageSetReviewNode,
        DeliveryNode,
    )
)


image_workflow_module_graph = ModuleGraphSpec(
    name="image_post_workflow",
    modules=[
        ModuleNodeSpec(
            name="research",
            input_refs=["workflow_invocation"],
            output_ref="research",
            subnodes=["search", "synthesis", "review"],
        ),
        ModuleNodeSpec(
            name="grouping",
            input_refs=["workflow_invocation", "research"],
            output_ref="grouping",
            subnodes=["grouping", "review"],
        ),
        ModuleNodeSpec(
            name="content",
            input_refs=["workflow_invocation", "research", "grouping"],
            output_ref="content",
            subnodes=["generate", "review"],
        ),
        ModuleNodeSpec(
            name="image",
            input_refs=["workflow_invocation", "grouping", "content"],
            output_ref="images",
            subnodes=[
                "reference_analysis",
                "image_planner",
                "image_task_subgraph",
                "image_join",
                "image_set_review",
            ],
            subgraphs={
                "image_task_subgraph": [
                    "prompt",
                    "image_generation",
                    "image_review",
                    "repair_retry",
                ],
            },
            supports_parallel=True,
        ),
        ModuleNodeSpec(
            name="delivery",
            input_refs=["workflow_invocation", "research", "grouping", "content", "images"],
            output_ref="delivery",
            subnodes=["package", "review", "feishu_delivery"],
        ),
    ],
)


class ImageWorkflowRunner:
    def __init__(self, *, deps: ImageWorkflowDeps):
        self.deps = deps
        self.graph = image_workflow_graph

    async def run(
        self,
        *,
        topic: str,
        audience: str,
        run_id: str,
        workspace_dir: Path,
        execution_text: str = "",
        invocation: WorkflowInvocation | None = None,
        image_count: int | None = None,
        single_item_per_image: bool = False,
        max_auto_images: int | None = ImageConfig.MAX_AUTO_IMAGES,
        image_generation_concurrency: int = 3,
        image_task_max_retries: int = 1,
    ) -> ResultEnvelope[DeliveryPackage]:
        state = ImageWorkflowState(
            topic=topic,
            audience=audience,
            run_id=run_id,
            workspace_dir=workspace_dir,
            execution_text=execution_text,
            invocation=invocation,
            image_count=image_count,
            single_item_per_image=single_item_per_image,
            max_auto_images=max_auto_images,
            image_generation_concurrency=image_generation_concurrency,
            image_task_max_retries=image_task_max_retries,
        )
        result = await self.graph.run(
            ResearchNode(),
            state=state,
            deps=self.deps,
        )
        return result.output


def _callable_accepts_param(func: Callable[..., object], param_name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    return param_name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
