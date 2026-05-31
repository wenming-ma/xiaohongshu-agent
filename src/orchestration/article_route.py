from __future__ import annotations

from datetime import datetime
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
from .schemas import ArtifactRef, DeliveryPackage, DeliveryTextBlock, ResultEnvelope
from .style_context import StyleContext
from .workspace import WorkflowWorkspace


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
    ) -> None:
        self.workspace_root = workspace_root or PathConfig.ORCHESTRATION_RUN_DIR
        self.delivery_sender = delivery_sender
        self.research_agent_factory = research_agent_factory
        self.content_agent_factory = content_agent_factory
        self.image_agent_factory = image_agent_factory

    async def run(
        self,
        request: ConversationRequest,
        *,
        run_id: str | None = None,
        chat_id: str | None = None,
        send_to_feishu: bool = False,
        style_context: StyleContext | None = None,
        run_options: Any | None = None,
    ) -> ResultEnvelope[DeliveryPackage]:
        brief = build_request_brief(request)
        style_context = style_context or StyleContext.from_request(request)
        resolved_run_id = run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_slug(brief.topic)}"
        workspace = WorkflowWorkspace.create(
            root_dir=self.workspace_root,
            run_id=resolved_run_id,
            route="article_post",
            topic=brief.topic,
            audience=brief.audience,
        )

        research = await self.research_agent_factory().forward(
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

        content = await self.content_agent_factory().forward(
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

        images = await self.image_agent_factory().forward(
            content=content,
            research=research,
            topic=brief.execution_text,
            target_audience=brief.audience,
            output_dir=workspace.run_dir,
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
