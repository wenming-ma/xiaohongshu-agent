from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from src.agents.image_post.schemas import GroupSpec, ImageResult, ResearchResult, XHSContent

from .schemas import DeliveryPackage, GroupingItem, GroupingResult, ImageTaskPlan, ResultEnvelope, WorkflowInvocation
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
    max_auto_images: int | None = 5
    image_generation_concurrency: int = 3
    research: ResultEnvelope[ResearchResult] | None = None
    groups: ResultEnvelope[GroupingResult] | None = None
    content: ResultEnvelope[XHSContent] | None = None
    image_plan: ImageTaskPlan | None = None
    images: list[ResultEnvelope[ImageResult]] = field(default_factory=list)
    delivery: ResultEnvelope[DeliveryPackage] | None = None


@dataclass
class ResearchNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "GroupingNode":
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

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImagePlannerNode":
        result = await ctx.deps.run_content(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            groups=self.groups,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.content = result
        return ImagePlannerNode(research=self.research, groups=self.groups, content=result)


@dataclass
class ImagePlannerNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImagesNode":
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
        )
        ctx.state.image_plan = image_plan
        return ImagesNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            image_plan=image_plan,
        )


@dataclass
class ImageTaskSubgraph:
    """Executable subgraph boundary for one image task plan."""

    deps: ImageWorkflowDeps

    async def run(
        self,
        *,
        state: ImageWorkflowState,
        research: ResultEnvelope[ResearchResult],
        content: ResultEnvelope[XHSContent],
        image_task: object,
        index: int,
    ) -> ResultEnvelope[ImageResult]:
        params = {
            "topic": state.topic,
            "execution_text": state.execution_text or state.topic,
            "group": image_task.to_group_payload(),
            "group_index": index,
            "research": research,
            "content": content,
            "run_id": state.run_id,
            "workspace_dir": state.workspace_dir,
        }
        if _callable_accepts_param(self.deps.run_image_group, "image_task"):
            params["image_task"] = image_task
        return await self.deps.run_image_group(**params)


@dataclass
class ImagesNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]
    image_plan: ImageTaskPlan

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "DeliveryNode":

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
        return DeliveryNode(
            research=self.research,
            groups=self.groups,
            content=self.content,
            images=list(images),
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
        ctx.state.delivery = result
        return End(result)


image_workflow_graph = Graph(
    nodes=(
        ResearchNode,
        GroupingNode,
        ContentNode,
        ImagePlannerNode,
        ImagesNode,
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
        max_auto_images: int | None = 5,
        image_generation_concurrency: int = 3,
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
