from __future__ import annotations

from datetime import datetime
import inspect
from pathlib import Path
import mimetypes
import re
from typing import Any

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
        },
    )


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

        research = await research_agent.forward(
            topic=brief.execution_text,
            target_audience=brief.audience,
            strategy=ArticleStrategy.AUTO,
            output_dir=workspace.run_dir,
        )
        research_envelope = ResultEnvelope[ArticleResearchResult].success(
            agent_name="research_agent",
            payload=research,
            summary=research.summary or f"{brief.topic} 长文调研完成",
            run_id=resolved_run_id,
            step_id="research",
        )
        workspace.save_envelope(research_envelope, label="research")

        content = await content_agent.forward(
            research=research,
            topic=brief.execution_text,
            target_audience=brief.audience,
            requested_strategy=ArticleStrategy.AUTO,
            generate_images=True,
            output_dir=workspace.run_dir,
        )
        content_envelope = ResultEnvelope[XHSArticleContent].success(
            agent_name="content_agent",
            payload=content,
            summary=f"长文内容生成完成：{content.title}",
            run_id=resolved_run_id,
            step_id="content",
        )
        workspace.save_envelope(content_envelope, label="content")

        images = await image_agent.forward(
            content=content,
            research=research,
            topic=brief.execution_text,
            target_audience=brief.audience,
            output_dir=workspace.run_dir,
            max_images=brief.image_count or resolved_run_options.image.max_images,
        )
        image_artifacts = [
            _image_artifact(image, style_context=style_context)
            for image in images.images
        ]
        image_envelope = ResultEnvelope[ArticleImageResult].success(
            agent_name="image_generation_agent",
            payload=images,
            summary=f"长文配图生成完成：{images.total_count} 张",
            run_id=resolved_run_id,
            step_id="image",
            artifacts=image_artifacts,
        )
        workspace.save_envelope(image_envelope, label="image")

        package = _build_article_delivery_package(
            brief=brief,
            research=research,
            content=content,
            images=images,
            style_context=style_context,
            run_options=resolved_run_options,
        )
        envelope = ResultEnvelope[DeliveryPackage].success(
            agent_name="review_delivery_agent",
            payload=package,
            summary=package.summary,
            run_id=resolved_run_id,
            step_id="delivery",
            artifacts=package.artifacts,
        )
        workspace.save_envelope(envelope, label="delivery")

        if send_to_feishu and self.delivery_sender is not None:
            await self.delivery_sender.send(envelope, chat_id=chat_id)

        return envelope
