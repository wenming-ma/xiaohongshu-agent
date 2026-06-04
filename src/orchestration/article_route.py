from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import inspect
from pathlib import Path
import mimetypes
import re
from typing import Any, Awaitable, Callable

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from src.agents.article_post.content.agent import ContentAgent
from src.agents.article_post.image.agent import ImageAgent
from src.agents.article_post.research.agent import ResearchAgent
from src.agents.article_post.schemas import (
    ArticleImageResult,
    ArticleResearchResult,
    ArticleStrategy,
    GeneratedArticleImage,
    XHSArticleContent,
)
from src.config.settings import PathConfig

from .conversation import ConversationRequest
from .request_brief import RequestBrief, build_request_brief
from .run_options import ArticlePostRunOptions
from .schemas import ArtifactRef, DeliveryPackage, DeliveryTextBlock, ResultEnvelope, WorkflowInvocation
from .style_context import StyleContext
from .workflow_graph import ModuleGraphSpec, ModuleNodeSpec
from .workspace import WorkflowWorkspace


article_workflow_module_graph = ModuleGraphSpec(
    name="article_post_workflow",
    modules=[
        ModuleNodeSpec(
            name="research",
            input_refs=["workflow_invocation"],
            output_ref="research",
            subnodes=["search", "synthesis", "review"],
        ),
        ModuleNodeSpec(
            name="content",
            input_refs=["workflow_invocation", "research"],
            output_ref="content",
            subnodes=["generate", "review"],
        ),
        ModuleNodeSpec(
            name="image",
            input_refs=["workflow_invocation", "research", "content"],
            output_ref="image",
            subnodes=["image_planner", "image_generation", "image_review"],
        ),
        ModuleNodeSpec(
            name="delivery",
            input_refs=["workflow_invocation", "research", "content", "image"],
            output_ref="delivery",
            subnodes=["package", "review", "feishu_delivery"],
        ),
    ],
)


def _safe_slug(value: str, *, max_length: int = 24) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value).strip("-")
    return (cleaned or "run")[:max_length]


def _guess_mime_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _image_artifact(image: GeneratedArticleImage, *, style_context: StyleContext) -> ArtifactRef:
    return ArtifactRef(
        artifact_type="image",
        label=image.image_key,
        path=image.image_path,
        mime_type=_guess_mime_type(image.image_path),
        metadata={
            "style_context": style_context.metadata(),
            "prompt_summary": image.prompt_used[:500],
        },
    )


def _build_article_delivery_package(
    *,
    brief: RequestBrief,
    research: ArticleResearchResult,
    content: XHSArticleContent,
    images: ArticleImageResult,
    style_context: StyleContext,
    run_options: ArticlePostRunOptions | None = None,
) -> DeliveryPackage:
    hashtags = " ".join(f"#{tag}" for tag in content.hashtags)
    artifacts = [
        _image_artifact(image, style_context=style_context)
        for image in images.images
    ]
    return DeliveryPackage(
        route="article_post",
        title=content.title or brief.topic,
        summary=f"{brief.topic} 的长文飞书交付包已整理完成",
        text_blocks=[
            DeliveryTextBlock(label="topic", text=f"主题：{brief.topic}"),
            DeliveryTextBlock(label="audience", text=f"受众：{brief.audience}"),
            DeliveryTextBlock(label="requirements", text=brief.requirements_text),
            DeliveryTextBlock(label="title", text=f"标题：{content.title}"),
            DeliveryTextBlock(label="body", text=f"正文：{content.rendered_body or content.lead}"),
            DeliveryTextBlock(label="hashtags", text=f"话题：{hashtags or '无'}"),
            DeliveryTextBlock(label="research_summary", text=f"调研摘要：{research.summary}"),
        ],
        artifacts=artifacts,
        metadata={
            "topic": brief.topic,
            "audience": brief.audience,
            "style_constraints": list(brief.style_constraints),
            "style_context": style_context.metadata(),
            "source_count": research.sources_count,
            "image_count": len(artifacts),
            "run_options": run_options.model_dump(mode="json") if run_options is not None else {},
            "workflow_graph": {
                "name": article_workflow_module_graph.name,
                "modules": article_workflow_module_graph.describe(),
            },
            "workflow_runner": "ArticleWorkflowRunner",
        },
    )


ArticleResearchRunner = Callable[..., Awaitable[ResultEnvelope[ArticleResearchResult]]]
ArticleContentRunner = Callable[..., Awaitable[ResultEnvelope[XHSArticleContent]]]
ArticleImageRunner = Callable[..., Awaitable[ResultEnvelope[ArticleImageResult]]]
ArticleDeliveryRunner = Callable[..., Awaitable[ResultEnvelope[DeliveryPackage]]]


@dataclass
class ArticleWorkflowDeps:
    run_research: ArticleResearchRunner
    run_content: ArticleContentRunner
    run_image: ArticleImageRunner
    run_delivery: ArticleDeliveryRunner


@dataclass
class ArticleWorkflowState:
    topic: str
    audience: str
    run_id: str
    workspace_dir: Path
    execution_text: str = ""
    invocation: WorkflowInvocation | None = None
    image_count: int | None = None
    research: ResultEnvelope[ArticleResearchResult] | None = None
    content: ResultEnvelope[XHSArticleContent] | None = None
    image: ResultEnvelope[ArticleImageResult] | None = None
    delivery: ResultEnvelope[DeliveryPackage] | None = None


@dataclass
class ArticleResearchNode(BaseNode[ArticleWorkflowState, ArticleWorkflowDeps]):
    async def run(self, ctx: GraphRunContext[ArticleWorkflowState, ArticleWorkflowDeps]) -> "ArticleContentNode":
        result = await ctx.deps.run_research(
            topic=ctx.state.topic,
            audience=ctx.state.audience,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.research = result
        return ArticleContentNode(research=result)


@dataclass
class ArticleContentNode(BaseNode[ArticleWorkflowState, ArticleWorkflowDeps]):
    research: ResultEnvelope[ArticleResearchResult]

    async def run(self, ctx: GraphRunContext[ArticleWorkflowState, ArticleWorkflowDeps]) -> "ArticleImageNode":
        result = await ctx.deps.run_content(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.content = result
        return ArticleImageNode(research=self.research, content=result)


@dataclass
class ArticleImageNode(BaseNode[ArticleWorkflowState, ArticleWorkflowDeps]):
    research: ResultEnvelope[ArticleResearchResult]
    content: ResultEnvelope[XHSArticleContent]

    async def run(self, ctx: GraphRunContext[ArticleWorkflowState, ArticleWorkflowDeps]) -> "ArticleDeliveryNode":
        result = await ctx.deps.run_image(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            content=self.content,
            requested_image_count=ctx.state.image_count,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.image = result
        return ArticleDeliveryNode(research=self.research, content=self.content, image=result)


@dataclass
class ArticleDeliveryNode(BaseNode[ArticleWorkflowState, ArticleWorkflowDeps, ResultEnvelope[DeliveryPackage]]):
    research: ResultEnvelope[ArticleResearchResult]
    content: ResultEnvelope[XHSArticleContent]
    image: ResultEnvelope[ArticleImageResult]

    async def run(
        self,
        ctx: GraphRunContext[ArticleWorkflowState, ArticleWorkflowDeps],
    ) -> End[ResultEnvelope[DeliveryPackage]]:
        result = await ctx.deps.run_delivery(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            content=self.content,
            image=self.image,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.delivery = result
        return End(result)


article_workflow_graph = Graph(
    nodes=(
        ArticleResearchNode,
        ArticleContentNode,
        ArticleImageNode,
        ArticleDeliveryNode,
    )
)


class ArticleWorkflowRunner:
    def __init__(self, *, deps: ArticleWorkflowDeps):
        self.deps = deps
        self.graph = article_workflow_graph

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
    ) -> ResultEnvelope[DeliveryPackage]:
        state = ArticleWorkflowState(
            topic=topic,
            audience=audience,
            run_id=run_id,
            workspace_dir=workspace_dir,
            execution_text=execution_text,
            invocation=invocation,
            image_count=image_count,
        )
        result = await self.graph.run(
            ArticleResearchNode(),
            state=state,
            deps=self.deps,
        )
        return result.output


class ArticlePostOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        delivery_sender: Any | None = None,
        research_agent_factory: type[ResearchAgent] = ResearchAgent,
        content_agent_factory: type[ContentAgent] = ContentAgent,
        image_agent_factory: type[ImageAgent] = ImageAgent,
        run_options: ArticlePostRunOptions | None = None,
    ) -> None:
        self.workspace_root = workspace_root or PathConfig.ORCHESTRATION_RUN_DIR
        self.delivery_sender = delivery_sender
        self.research_agent_factory = research_agent_factory
        self.content_agent_factory = content_agent_factory
        self.image_agent_factory = image_agent_factory
        self.run_options = run_options or ArticlePostRunOptions()

    @staticmethod
    def _instantiate_agent(factory: Any, *, run_options: Any | None = None) -> Any:
        if run_options is None:
            return factory()
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            return factory(run_options=run_options)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if "run_options" in signature.parameters or accepts_kwargs:
            return factory(run_options=run_options)
        return factory()

    async def run(
        self,
        request: ConversationRequest,
        *,
        run_id: str | None = None,
        chat_id: str | None = None,
        send_to_feishu: bool = False,
        style_context: StyleContext | None = None,
        run_options: ArticlePostRunOptions | None = None,
    ) -> ResultEnvelope[DeliveryPackage]:
        brief = build_request_brief(request)
        style_context = style_context or StyleContext.from_request(request)
        resolved_run_options = (
            run_options
            if isinstance(run_options, ArticlePostRunOptions)
            else self.run_options or ArticlePostRunOptions()
        )
        resolved_run_id = run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_slug(brief.topic)}"
        workspace = WorkflowWorkspace.create(
            root_dir=self.workspace_root,
            run_id=resolved_run_id,
            route="article_post",
            topic=brief.topic,
            audience=brief.audience,
        )
        workflow_invocation = WorkflowInvocation(
            objective=brief.execution_text,
            route="article_post",
            topic=brief.topic,
            audience=brief.audience,
            selected_skills=list(style_context.matched_skills),
            selected_prompt_templates=[ref.source for ref in style_context.prompt_refs],
            user_requirements=[brief.requirements_text] if brief.requirements_text else [],
            constraints=[
                *brief.style_constraints,
                *style_context.hard_constraints,
                *style_context.negative_constraints,
            ],
            artifacts=[
                ArtifactRef(
                    artifact_type="image",
                    label=ref.label,
                    path=ref.path,
                    mime_type=ref.mime_type,
                )
                for ref in style_context.reference_images
            ],
            run_options=resolved_run_options.model_dump(mode="json"),
            delivery={"target": "feishu", "chat_id": chat_id},
        )
        workspace.save_invocation(workflow_invocation)

        research_agent = self._instantiate_agent(
            self.research_agent_factory,
            run_options=resolved_run_options.research,
        )
        content_agent = self._instantiate_agent(
            self.content_agent_factory,
            run_options=resolved_run_options.content,
        )
        image_agent = self.image_agent_factory()

        async def run_research(**kwargs: Any) -> ResultEnvelope[ArticleResearchResult]:
            research = await research_agent.forward(
                topic=kwargs["execution_text"],
                target_audience=kwargs["audience"],
                strategy=ArticleStrategy.AUTO,
                output_dir=kwargs["workspace_dir"],
            )
            envelope = ResultEnvelope[ArticleResearchResult].success(
                agent_name="research_agent",
                payload=research,
                summary=research.summary or f"{brief.topic} 长文调研完成",
                run_id=kwargs["run_id"],
                step_id="research",
            )
            workspace.save_envelope(envelope, label="research")
            return envelope

        async def run_content(**kwargs: Any) -> ResultEnvelope[XHSArticleContent]:
            research_envelope = kwargs["research"]
            if research_envelope.payload is None:
                return ResultEnvelope[XHSArticleContent].error(
                    agent_name="content_agent",
                    summary="长文研究结果为空，无法生成内容",
                    error_message="article research payload is empty",
                    run_id=kwargs["run_id"],
                    step_id="content",
                )
            content = await content_agent.forward(
                research=research_envelope.payload,
                topic=kwargs["execution_text"],
                target_audience=brief.audience,
                requested_strategy=ArticleStrategy.AUTO,
                generate_images=True,
                output_dir=kwargs["workspace_dir"],
            )
            envelope = ResultEnvelope[XHSArticleContent].success(
                agent_name="content_agent",
                payload=content,
                summary=f"长文内容生成完成：{content.title}",
                run_id=kwargs["run_id"],
                step_id="content",
            )
            workspace.save_envelope(envelope, label="content")
            return envelope

        async def run_image(**kwargs: Any) -> ResultEnvelope[ArticleImageResult]:
            research_envelope = kwargs["research"]
            content_envelope = kwargs["content"]
            if research_envelope.payload is None or content_envelope.payload is None:
                return ResultEnvelope[ArticleImageResult].error(
                    agent_name="image_generation_agent",
                    summary="长文图片输入为空，无法生成配图",
                    error_message="article image inputs are empty",
                    run_id=kwargs["run_id"],
                    step_id="image",
                )
            images = await image_agent.forward(
                content=content_envelope.payload,
                research=research_envelope.payload,
                topic=kwargs["execution_text"],
                target_audience=brief.audience,
                output_dir=kwargs["workspace_dir"],
                max_images=brief.image_count or resolved_run_options.image.max_images,
            )
            image_artifacts = [
                _image_artifact(image, style_context=style_context)
                for image in images.images
            ]
            envelope = ResultEnvelope[ArticleImageResult].success(
                agent_name="image_generation_agent",
                payload=images,
                summary=f"长文配图生成完成：{images.total_count} 张",
                run_id=kwargs["run_id"],
                step_id="image",
                artifacts=image_artifacts,
            )
            workspace.save_envelope(envelope, label="image")
            return envelope

        async def run_delivery(**kwargs: Any) -> ResultEnvelope[DeliveryPackage]:
            research_envelope = kwargs["research"]
            content_envelope = kwargs["content"]
            image_envelope = kwargs["image"]
            if (
                research_envelope.payload is None
                or content_envelope.payload is None
                or image_envelope.payload is None
            ):
                return ResultEnvelope[DeliveryPackage].error(
                    agent_name="review_delivery_agent",
                    summary="长文交付输入为空，无法生成飞书交付包",
                    error_message="article delivery inputs are empty",
                    run_id=kwargs["run_id"],
                    step_id="delivery",
                    artifacts=image_envelope.artifacts,
                )
            package = _build_article_delivery_package(
                brief=brief,
                research=research_envelope.payload,
                content=content_envelope.payload,
                images=image_envelope.payload,
                style_context=style_context,
                run_options=resolved_run_options,
            )
            envelope = ResultEnvelope[DeliveryPackage].success(
                agent_name="review_delivery_agent",
                payload=package,
                summary=package.summary,
                run_id=kwargs["run_id"],
                step_id="delivery",
                artifacts=package.artifacts,
            )
            workspace.save_envelope(envelope, label="delivery")
            return envelope

        runner = ArticleWorkflowRunner(
            deps=ArticleWorkflowDeps(
                run_research=run_research,
                run_content=run_content,
                run_image=run_image,
                run_delivery=run_delivery,
            )
        )
        envelope = await runner.run(
            topic=brief.topic,
            audience=brief.audience,
            run_id=resolved_run_id,
            workspace_dir=workspace.run_dir,
            execution_text=brief.execution_text,
            invocation=workflow_invocation,
            image_count=brief.image_count,
        )

        if send_to_feishu and self.delivery_sender is not None:
            await self.delivery_sender.send(envelope, chat_id=chat_id)

        return envelope
