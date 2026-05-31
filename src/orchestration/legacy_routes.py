from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from src.agents.article_post import XHSArticlePostInput, XHSArticlePostPipeline
from src.agents.video_post.pipeline import XHSVideoPostPipeline
from src.agents.video_post.schemas import XHSVideoPostInput
from src.config.settings import PathConfig

from .conversation import ConversationRequest
from .request_brief import RequestBrief, build_request_brief
from .schemas import ArtifactRef, DeliveryPackage, DeliveryTextBlock, ResultEnvelope
from .workspace import WorkflowWorkspace


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guess_mime_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _artifact_from_path(path: str, *, label: str) -> ArtifactRef:
    artifact_type = "image"
    mime_type = _guess_mime_type(path)
    if mime_type.startswith("video/"):
        artifact_type = "video"
    return ArtifactRef(
        artifact_type=artifact_type,
        label=label,
        path=path,
        mime_type=mime_type,
    )


class _LegacyPipelineOrchestrator:
    route: str
    workspace_root: Path

    def __init__(self, *, workspace_root: Path | None = None, delivery_sender: Any | None = None) -> None:
        self.workspace_root = workspace_root or PathConfig.ORCHESTRATION_RUN_DIR
        self.delivery_sender = delivery_sender

    async def run(
        self,
        request: ConversationRequest,
        *,
        run_id: str | None = None,
        chat_id: str | None = None,
        send_to_feishu: bool = False,
    ) -> ResultEnvelope[DeliveryPackage]:
        brief = build_request_brief(request)
        resolved_run_id = run_id or self.route
        workspace = WorkflowWorkspace.create(
            root_dir=self.workspace_root,
            run_id=resolved_run_id,
            route=self.route,
            topic=brief.topic,
            audience=brief.audience,
        )
        result = await self._execute_pipeline(topic=brief.execution_text, audience=brief.audience)
        if not result.success:
            envelope = ResultEnvelope[DeliveryPackage].error(
                agent_name=f"{self.route}_runner",
                summary=f"{self.route} 交付失败",
                error_message=result.error_message or "unknown pipeline error",
                run_id=resolved_run_id,
                step_id="delivery",
            )
            workspace.save_envelope(envelope, label="delivery")
            return envelope

        package = self._build_delivery_package(brief=brief, pipeline_output=result)
        envelope = ResultEnvelope[DeliveryPackage].success(
            agent_name=f"{self.route}_runner",
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

    async def _execute_pipeline(self, *, topic: str, audience: str):
        raise NotImplementedError

    def _build_delivery_package(self, *, brief: RequestBrief, pipeline_output) -> DeliveryPackage:
        raise NotImplementedError


class ArticlePostOrchestrator(_LegacyPipelineOrchestrator):
    route = "article_post"

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        delivery_sender: Any | None = None,
        pipeline_factory: type[XHSArticlePostPipeline] = XHSArticlePostPipeline,
    ) -> None:
        super().__init__(workspace_root=workspace_root, delivery_sender=delivery_sender)
        self.pipeline_factory = pipeline_factory

    async def _execute_pipeline(self, *, topic: str, audience: str):
        pipeline = self.pipeline_factory()
        return await pipeline.execute(
            XHSArticlePostInput(
                topic=topic,
                audience=audience,
                publish=False,
            )
        )

    def _build_delivery_package(self, *, brief: RequestBrief, pipeline_output) -> DeliveryPackage:
        output_dir = Path(pipeline_output.output_dir)
        content_data = _read_json_file(output_dir / "content.json")
        body = content_data.get("rendered_body") or pipeline_output.body_preview or ""
        hashtags = " ".join(f"#{tag}" for tag in (pipeline_output.hashtags or []))
        artifacts = [
            _artifact_from_path(path, label=f"image_{index}")
            for index, path in enumerate(pipeline_output.image_paths or [], start=1)
        ]
        return DeliveryPackage(
            route=self.route,
            title=pipeline_output.title or brief.topic,
            summary=f"{brief.topic} 的长文交付包已整理完成",
            text_blocks=[
                DeliveryTextBlock(label="topic", text=f"主题：{brief.topic}"),
                DeliveryTextBlock(label="audience", text=f"受众：{brief.audience}"),
                DeliveryTextBlock(label="requirements", text=brief.requirements_text),
                DeliveryTextBlock(label="title", text=f"标题：{pipeline_output.title or brief.topic}"),
                DeliveryTextBlock(label="body", text=f"正文：{body}"),
                DeliveryTextBlock(label="hashtags", text=f"话题：{hashtags or '无'}"),
            ],
            artifacts=artifacts,
            metadata={"output_dir": str(output_dir), "style_constraints": list(brief.style_constraints)},
        )


class VideoPostOrchestrator(_LegacyPipelineOrchestrator):
    route = "video_post"

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        delivery_sender: Any | None = None,
        pipeline_factory: type[XHSVideoPostPipeline] = XHSVideoPostPipeline,
    ) -> None:
        super().__init__(workspace_root=workspace_root, delivery_sender=delivery_sender)
        self.pipeline_factory = pipeline_factory

    async def _execute_pipeline(self, *, topic: str, audience: str):
        pipeline = self.pipeline_factory()
        return await pipeline.execute(
            XHSVideoPostInput(
                topic=topic,
                audience=audience,
                publish=False,
            )
        )

    def _build_delivery_package(self, *, brief: RequestBrief, pipeline_output) -> DeliveryPackage:
        output_dir = Path(pipeline_output.output_dir)
        content_data = _read_json_file(output_dir / "content.json")
        body = content_data.get("body") or pipeline_output.body_preview or ""
        hashtags = " ".join(f"#{tag}" for tag in (pipeline_output.hashtags or []))
        artifacts: list[ArtifactRef] = []
        if pipeline_output.video_path:
            artifacts.append(_artifact_from_path(pipeline_output.video_path, label="video"))
        return DeliveryPackage(
            route=self.route,
            title=pipeline_output.title or brief.topic,
            summary=f"{brief.topic} 的视频交付包已整理完成",
            text_blocks=[
                DeliveryTextBlock(label="topic", text=f"主题：{brief.topic}"),
                DeliveryTextBlock(label="audience", text=f"受众：{brief.audience}"),
                DeliveryTextBlock(label="requirements", text=brief.requirements_text),
                DeliveryTextBlock(label="title", text=f"标题：{pipeline_output.title or brief.topic}"),
                DeliveryTextBlock(label="body", text=f"正文：{body}"),
                DeliveryTextBlock(label="hashtags", text=f"话题：{hashtags or '无'}"),
            ],
            artifacts=artifacts,
            metadata={"output_dir": str(output_dir), "style_constraints": list(brief.style_constraints)},
        )
