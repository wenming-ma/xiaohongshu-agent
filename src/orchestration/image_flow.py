from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from src.agents.image_post.schemas import GroupSpec, ImageResult, ResearchResult, XHSContent

from .schemas import DeliveryPackage, GroupingItem, GroupingResult, ResultEnvelope


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
    image_count: int | None = None
    single_item_per_image: bool = False
    research: ResultEnvelope[ResearchResult] | None = None
    groups: ResultEnvelope[GroupingResult] | None = None
    content: ResultEnvelope[XHSContent] | None = None
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

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "ImagesNode":
        result = await ctx.deps.run_content(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            groups=self.groups,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.content = result
        return ImagesNode(research=self.research, groups=self.groups, content=result)


@dataclass
class ImagesNode(BaseNode[ImageWorkflowState, ImageWorkflowDeps]):
    research: ResultEnvelope[ResearchResult]
    groups: ResultEnvelope[GroupingResult]
    content: ResultEnvelope[XHSContent]

    async def run(self, ctx: GraphRunContext[ImageWorkflowState, ImageWorkflowDeps]) -> "DeliveryNode":
        groups = list((self.groups.payload or GroupingResult()).groups)
        if ctx.state.single_item_per_image and groups:
            group_specs = [
                {
                    "title": groups[0].title,
                    "indices": list(groups[0].indices),
                    "image_type": "cover",
                    "desc": f"封面图 - 单套展示：{groups[0].title}",
                }
            ]
            group_specs.extend(
                {
                    "title": group.title,
                    "indices": list(group.indices),
                    "image_type": f"detail_{index}",
                }
                for index, group in enumerate(groups[1:], start=1)
            )
        else:
            group_specs = [
                {"title": "封面", "indices": [], "image_type": "cover"},
                *[
                    {
                        "title": group.title,
                        "indices": list(group.indices),
                        "image_type": f"detail_{index}",
                    }
                    for index, group in enumerate(groups, start=1)
                ],
            ]
        if ctx.state.image_count is not None:
            target_count = max(1, min(ctx.state.image_count, 20))
            group_specs = group_specs[:target_count]
        images = await asyncio.gather(
            *[
                ctx.deps.run_image_group(
                    topic=ctx.state.topic,
                    execution_text=ctx.state.execution_text or ctx.state.topic,
                    group=group,
                    group_index=index,
                    research=self.research,
                    content=self.content,
                    run_id=ctx.state.run_id,
                    workspace_dir=ctx.state.workspace_dir,
                )
                for index, group in enumerate(group_specs)
            ]
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
        ImagesNode,
        DeliveryNode,
    )
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
        image_count: int | None = None,
        single_item_per_image: bool = False,
    ) -> ResultEnvelope[DeliveryPackage]:
        state = ImageWorkflowState(
            topic=topic,
            audience=audience,
            run_id=run_id,
            workspace_dir=workspace_dir,
            execution_text=execution_text,
            image_count=image_count,
            single_item_per_image=single_item_per_image,
        )
        result = await self.graph.run(
            ResearchNode(),
            state=state,
            deps=self.deps,
        )
        return result.output
