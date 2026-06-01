from __future__ import annotations

from datetime import datetime
from pathlib import Path
import mimetypes
import re
from typing import Any

from src.agents.video_post.content.agent import ContentAgent
from src.agents.video_post.cover.agent import CoverAgent
from src.agents.video_post.download.agent import DownloadAgent
from src.agents.video_post.research.agent import ResearchAgent
from src.agents.video_post.schemas import (
    CoverImageResult,
    DownloadResult,
    Platform,
    VideoResearchResult,
    XHSVideoContent,
)
from src.config.settings import PathConfig

from .conversation import ConversationRequest
from .request_brief import RequestBrief, build_request_brief
from .run_options import VideoPostRunOptions
from .schemas import ArtifactRef, DeliveryPackage, DeliveryTextBlock, ResultEnvelope
from .style_context import StyleContext
from .workspace import WorkflowWorkspace


def _safe_slug(value: str, *, max_length: int = 24) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value).strip("-")
    return (cleaned or "run")[:max_length]


def _guess_mime_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _artifact_from_path(
    path: str,
    *,
    label: str,
    artifact_type: str,
    style_context: StyleContext,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_type=artifact_type,
        label=label,
        path=path,
        mime_type=_guess_mime_type(path),
        metadata={"style_context": style_context.metadata()},
    )


def _build_video_delivery_package(
    *,
    brief: RequestBrief,
    research: VideoResearchResult,
    download: DownloadResult,
    content: XHSVideoContent,
    cover: CoverImageResult | None,
    style_context: StyleContext,
    run_options: VideoPostRunOptions,
) -> DeliveryPackage:
    artifacts = [
        _artifact_from_path(
            download.local_path,
            label="video",
            artifact_type="video",
            style_context=style_context,
        )
    ]
    if cover is not None and cover.success and cover.cover_path:
        artifacts.append(
            _artifact_from_path(
                cover.cover_path,
                label="cover",
                artifact_type="image",
                style_context=style_context,
            )
        )
    hashtags = " ".join(f"#{tag}" for tag in content.hashtags)
    return DeliveryPackage(
        route="video_post",
        title=content.title or brief.topic,
        summary=f"{brief.topic} 的视频飞书交付包已整理完成",
        text_blocks=[
            DeliveryTextBlock(label="topic", text=f"主题：{brief.topic}"),
            DeliveryTextBlock(label="audience", text=f"受众：{brief.audience}"),
            DeliveryTextBlock(label="requirements", text=brief.requirements_text),
            DeliveryTextBlock(label="title", text=f"标题：{content.title}"),
            DeliveryTextBlock(label="body", text=f"正文：{content.body}"),
            DeliveryTextBlock(label="hashtags", text=f"话题：{hashtags or '无'}"),
            DeliveryTextBlock(label="research_summary", text=f"视频调研摘要：{research.summary}"),
        ],
        artifacts=artifacts,
        metadata={
            "topic": brief.topic,
            "audience": brief.audience,
            "style_constraints": list(brief.style_constraints),
            "style_context": style_context.metadata(),
            "run_options": run_options.model_dump(mode="json"),
            "source_count": research.sources_count,
            "video_path": download.local_path,
            "cover_path": cover.cover_path if cover is not None else "",
        },
    )


class VideoPostOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        delivery_sender: Any | None = None,
        research_agent_factory: type[ResearchAgent] = ResearchAgent,
        download_agent_factory: type[DownloadAgent] = DownloadAgent,
        content_agent_factory: type[ContentAgent] = ContentAgent,
        cover_agent_factory: type[CoverAgent] = CoverAgent,
        run_options: VideoPostRunOptions | None = None,
    ) -> None:
        self.workspace_root = workspace_root or PathConfig.ORCHESTRATION_RUN_DIR
        self.delivery_sender = delivery_sender
        self.research_agent_factory = research_agent_factory
        self.download_agent_factory = download_agent_factory
        self.content_agent_factory = content_agent_factory
        self.cover_agent_factory = cover_agent_factory
        self.run_options = run_options or VideoPostRunOptions()

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
        resolved_run_options = (
            run_options
            if isinstance(run_options, VideoPostRunOptions)
            else self.run_options
        )
        resolved_run_id = run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_slug(brief.topic)}"
        workspace = WorkflowWorkspace.create(
            root_dir=self.workspace_root,
            run_id=resolved_run_id,
            route="video_post",
            topic=brief.topic,
            audience=brief.audience,
        )

        research = await self.research_agent_factory(
            run_options=resolved_run_options.research
        ).forward(
            topic=brief.execution_text,
            platforms=list(Platform),
            max_videos=resolved_run_options.research.max_videos,
            output_dir=workspace.run_dir,
        )
        research_envelope = ResultEnvelope[VideoResearchResult].success(
            agent_name="research_agent",
            payload=research,
            summary=research.summary or f"{brief.topic} 视频调研完成",
            run_id=resolved_run_id,
            step_id="research",
        )
        workspace.save_envelope(research_envelope, label="research")

        download = await self.download_agent_factory().forward(
            sources=research.sources,
            output_dir=workspace.run_dir,
            topic=brief.execution_text,
        )
        if not download.success:
            return ResultEnvelope[DeliveryPackage].error(
                agent_name="download_agent",
                summary="视频下载失败，无法生成飞书交付包",
                error_message=download.error_message or "download failed",
                run_id=resolved_run_id,
                step_id="download",
            )
        download_artifact = _artifact_from_path(
            download.local_path,
            label="video",
            artifact_type="video",
            style_context=style_context,
        )
        download_envelope = ResultEnvelope[DownloadResult].success(
            agent_name="download_agent",
            payload=download,
            summary="视频下载完成",
            run_id=resolved_run_id,
            step_id="download",
            artifacts=[download_artifact],
        )
        workspace.save_envelope(download_envelope, label="download")

        content = await self.content_agent_factory().forward(
            research=research,
            video_source=download.source,
            topic=brief.execution_text,
            transcript=download.transcription,
        )
        content_envelope = ResultEnvelope[XHSVideoContent].success(
            agent_name="content_agent",
            payload=content,
            summary=f"视频文案生成完成：{content.title}",
            run_id=resolved_run_id,
            step_id="content",
        )
        workspace.save_envelope(content_envelope, label="content")

        cover = await self.cover_agent_factory().forward(
            video_path=Path(download.local_path),
            content=content,
            topic=brief.execution_text,
            output_dir=workspace.run_dir,
        )
        cover_artifacts = []
        if cover.success and cover.cover_path:
            cover_artifacts.append(
                _artifact_from_path(
                    cover.cover_path,
                    label="cover",
                    artifact_type="image",
                    style_context=style_context,
                )
            )
        cover_envelope = ResultEnvelope[CoverImageResult].success(
            agent_name="cover_agent",
            payload=cover,
            summary="视频封面处理完成" if cover.success else "视频封面生成失败，保留视频交付",
            run_id=resolved_run_id,
            step_id="cover",
            artifacts=cover_artifacts,
        )
        workspace.save_envelope(cover_envelope, label="cover")

        package = _build_video_delivery_package(
            brief=brief,
            research=research,
            download=download,
            content=content,
            cover=cover,
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
