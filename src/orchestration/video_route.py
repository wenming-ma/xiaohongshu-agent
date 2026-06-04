from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import mimetypes
import re
from typing import Any, Awaitable, Callable

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

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
from .schemas import ArtifactRef, DeliveryPackage, DeliveryTextBlock, ResultEnvelope, WorkflowInvocation
from .style_context import StyleContext
from .workflow_graph import ModuleGraphSpec, ModuleNodeSpec
from .workspace import WorkflowWorkspace


video_workflow_module_graph = ModuleGraphSpec(
    name="video_post_workflow",
    modules=[
        ModuleNodeSpec(
            name="research",
            input_refs=["workflow_invocation"],
            output_ref="research",
            subnodes=["search", "selection", "review"],
        ),
        ModuleNodeSpec(
            name="download",
            input_refs=["workflow_invocation", "research"],
            output_ref="download",
            subnodes=["source_selection", "download", "transcription"],
        ),
        ModuleNodeSpec(
            name="content",
            input_refs=["workflow_invocation", "research", "download"],
            output_ref="content",
            subnodes=["generate", "review"],
        ),
        ModuleNodeSpec(
            name="cover",
            input_refs=["workflow_invocation", "download", "content"],
            output_ref="cover",
            subnodes=["frame_selection", "cover_generation", "review"],
        ),
        ModuleNodeSpec(
            name="delivery",
            input_refs=["workflow_invocation", "research", "download", "content", "cover"],
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
            "workflow_graph": {
                "name": video_workflow_module_graph.name,
                "modules": video_workflow_module_graph.describe(),
            },
            "workflow_runner": "VideoWorkflowRunner",
        },
    )


VideoResearchRunner = Callable[..., Awaitable[ResultEnvelope[VideoResearchResult]]]
VideoDownloadRunner = Callable[..., Awaitable[ResultEnvelope[DownloadResult]]]
VideoContentRunner = Callable[..., Awaitable[ResultEnvelope[XHSVideoContent]]]
VideoCoverRunner = Callable[..., Awaitable[ResultEnvelope[CoverImageResult]]]
VideoDeliveryRunner = Callable[..., Awaitable[ResultEnvelope[DeliveryPackage]]]


@dataclass
class VideoWorkflowDeps:
    run_research: VideoResearchRunner
    run_download: VideoDownloadRunner
    run_content: VideoContentRunner
    run_cover: VideoCoverRunner
    run_delivery: VideoDeliveryRunner


@dataclass
class VideoWorkflowState:
    topic: str
    audience: str
    run_id: str
    workspace_dir: Path
    execution_text: str = ""
    invocation: WorkflowInvocation | None = None
    research: ResultEnvelope[VideoResearchResult] | None = None
    download: ResultEnvelope[DownloadResult] | None = None
    content: ResultEnvelope[XHSVideoContent] | None = None
    cover: ResultEnvelope[CoverImageResult] | None = None
    delivery: ResultEnvelope[DeliveryPackage] | None = None


@dataclass
class VideoResearchNode(BaseNode[VideoWorkflowState, VideoWorkflowDeps]):
    async def run(self, ctx: GraphRunContext[VideoWorkflowState, VideoWorkflowDeps]) -> "VideoDownloadNode":
        result = await ctx.deps.run_research(
            topic=ctx.state.topic,
            audience=ctx.state.audience,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.research = result
        return VideoDownloadNode(research=result)


@dataclass
class VideoDownloadNode(BaseNode[VideoWorkflowState, VideoWorkflowDeps, ResultEnvelope[DeliveryPackage]]):
    research: ResultEnvelope[VideoResearchResult]

    async def run(
        self,
        ctx: GraphRunContext[VideoWorkflowState, VideoWorkflowDeps],
    ) -> "VideoContentNode | End[ResultEnvelope[DeliveryPackage]]":
        result = await ctx.deps.run_download(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.download = result
        if result.status != "success" or result.payload is None or not result.payload.success:
            error_message = (
                result.error_message
                or (result.payload.error_message if result.payload is not None else "")
                or "download failed"
            )
            return End(
                ResultEnvelope[DeliveryPackage].error(
                    agent_name=result.agent_name,
                    summary="视频下载失败，无法生成飞书交付包",
                    error_message=error_message,
                    run_id=ctx.state.run_id,
                    step_id="download",
                    artifacts=result.artifacts,
                )
            )
        return VideoContentNode(research=self.research, download=result)


@dataclass
class VideoContentNode(BaseNode[VideoWorkflowState, VideoWorkflowDeps]):
    research: ResultEnvelope[VideoResearchResult]
    download: ResultEnvelope[DownloadResult]

    async def run(self, ctx: GraphRunContext[VideoWorkflowState, VideoWorkflowDeps]) -> "VideoCoverNode":
        result = await ctx.deps.run_content(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            download=self.download,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.content = result
        return VideoCoverNode(research=self.research, download=self.download, content=result)


@dataclass
class VideoCoverNode(BaseNode[VideoWorkflowState, VideoWorkflowDeps]):
    research: ResultEnvelope[VideoResearchResult]
    download: ResultEnvelope[DownloadResult]
    content: ResultEnvelope[XHSVideoContent]

    async def run(self, ctx: GraphRunContext[VideoWorkflowState, VideoWorkflowDeps]) -> "VideoDeliveryNode":
        result = await ctx.deps.run_cover(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            download=self.download,
            content=self.content,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.cover = result
        return VideoDeliveryNode(research=self.research, download=self.download, content=self.content, cover=result)


@dataclass
class VideoDeliveryNode(BaseNode[VideoWorkflowState, VideoWorkflowDeps, ResultEnvelope[DeliveryPackage]]):
    research: ResultEnvelope[VideoResearchResult]
    download: ResultEnvelope[DownloadResult]
    content: ResultEnvelope[XHSVideoContent]
    cover: ResultEnvelope[CoverImageResult]

    async def run(
        self,
        ctx: GraphRunContext[VideoWorkflowState, VideoWorkflowDeps],
    ) -> End[ResultEnvelope[DeliveryPackage]]:
        result = await ctx.deps.run_delivery(
            topic=ctx.state.topic,
            execution_text=ctx.state.execution_text or ctx.state.topic,
            research=self.research,
            download=self.download,
            content=self.content,
            cover=self.cover,
            run_id=ctx.state.run_id,
            workspace_dir=ctx.state.workspace_dir,
        )
        ctx.state.delivery = result
        return End(result)


video_workflow_graph = Graph(
    nodes=(
        VideoResearchNode,
        VideoDownloadNode,
        VideoContentNode,
        VideoCoverNode,
        VideoDeliveryNode,
    )
)


class VideoWorkflowRunner:
    def __init__(self, *, deps: VideoWorkflowDeps):
        self.deps = deps
        self.graph = video_workflow_graph

    async def run(
        self,
        *,
        topic: str,
        audience: str,
        run_id: str,
        workspace_dir: Path,
        execution_text: str = "",
        invocation: WorkflowInvocation | None = None,
    ) -> ResultEnvelope[DeliveryPackage]:
        state = VideoWorkflowState(
            topic=topic,
            audience=audience,
            run_id=run_id,
            workspace_dir=workspace_dir,
            execution_text=execution_text,
            invocation=invocation,
        )
        result = await self.graph.run(
            VideoResearchNode(),
            state=state,
            deps=self.deps,
        )
        return result.output


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
        workflow_invocation = WorkflowInvocation(
            objective=brief.execution_text,
            route="video_post",
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

        research_agent = self.research_agent_factory(
            run_options=resolved_run_options.research
        )
        download_agent = self.download_agent_factory()
        content_agent = self.content_agent_factory()
        cover_agent = self.cover_agent_factory()

        async def run_research(**kwargs: Any) -> ResultEnvelope[VideoResearchResult]:
            research = await research_agent.forward(
                topic=kwargs["execution_text"],
                platforms=list(Platform),
                max_videos=resolved_run_options.research.max_videos,
                output_dir=kwargs["workspace_dir"],
            )
            envelope = ResultEnvelope[VideoResearchResult].success(
                agent_name="research_agent",
                payload=research,
                summary=research.summary or f"{brief.topic} 视频调研完成",
                run_id=kwargs["run_id"],
                step_id="research",
            )
            workspace.save_envelope(envelope, label="research")
            return envelope

        async def run_download(**kwargs: Any) -> ResultEnvelope[DownloadResult]:
            research_envelope = kwargs["research"]
            if research_envelope.payload is None:
                envelope = ResultEnvelope[DownloadResult].error(
                    agent_name="download_agent",
                    summary="视频研究结果为空，无法下载",
                    error_message="video research payload is empty",
                    run_id=kwargs["run_id"],
                    step_id="download",
                )
                workspace.save_envelope(envelope, label="download")
                return envelope
            download = await download_agent.forward(
                sources=research_envelope.payload.sources,
                output_dir=kwargs["workspace_dir"],
                topic=kwargs["execution_text"],
            )
            if not download.success:
                envelope = ResultEnvelope[DownloadResult].error(
                    agent_name="download_agent",
                    summary="视频下载失败，无法生成飞书交付包",
                    error_message=download.error_message or "download failed",
                    run_id=kwargs["run_id"],
                    step_id="download",
                )
                workspace.save_envelope(envelope, label="download")
                return envelope
            download_artifact = _artifact_from_path(
                download.local_path,
                label="video",
                artifact_type="video",
                style_context=style_context,
            )
            envelope = ResultEnvelope[DownloadResult].success(
                agent_name="download_agent",
                payload=download,
                summary="视频下载完成",
                run_id=kwargs["run_id"],
                step_id="download",
                artifacts=[download_artifact],
            )
            workspace.save_envelope(envelope, label="download")
            return envelope

        async def run_content(**kwargs: Any) -> ResultEnvelope[XHSVideoContent]:
            research_envelope = kwargs["research"]
            download_envelope = kwargs["download"]
            if research_envelope.payload is None or download_envelope.payload is None:
                return ResultEnvelope[XHSVideoContent].error(
                    agent_name="content_agent",
                    summary="视频内容输入为空，无法生成文案",
                    error_message="video content inputs are empty",
                    run_id=kwargs["run_id"],
                    step_id="content",
                )
            content = await content_agent.forward(
                research=research_envelope.payload,
                video_source=download_envelope.payload.source,
                topic=kwargs["execution_text"],
                transcript=download_envelope.payload.transcription,
            )
            envelope = ResultEnvelope[XHSVideoContent].success(
                agent_name="content_agent",
                payload=content,
                summary=f"视频文案生成完成：{content.title}",
                run_id=kwargs["run_id"],
                step_id="content",
            )
            workspace.save_envelope(envelope, label="content")
            return envelope

        async def run_cover(**kwargs: Any) -> ResultEnvelope[CoverImageResult]:
            download_envelope = kwargs["download"]
            content_envelope = kwargs["content"]
            if download_envelope.payload is None or content_envelope.payload is None:
                return ResultEnvelope[CoverImageResult].error(
                    agent_name="cover_agent",
                    summary="视频封面输入为空，无法生成封面",
                    error_message="video cover inputs are empty",
                    run_id=kwargs["run_id"],
                    step_id="cover",
                )
            cover = await cover_agent.forward(
                video_path=Path(download_envelope.payload.local_path),
                content=content_envelope.payload,
                topic=kwargs["execution_text"],
                output_dir=kwargs["workspace_dir"],
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
            envelope = ResultEnvelope[CoverImageResult].success(
                agent_name="cover_agent",
                payload=cover,
                summary="视频封面处理完成" if cover.success else "视频封面生成失败，保留视频交付",
                run_id=kwargs["run_id"],
                step_id="cover",
                artifacts=cover_artifacts,
            )
            workspace.save_envelope(envelope, label="cover")
            return envelope

        async def run_delivery(**kwargs: Any) -> ResultEnvelope[DeliveryPackage]:
            research_envelope = kwargs["research"]
            download_envelope = kwargs["download"]
            content_envelope = kwargs["content"]
            cover_envelope = kwargs["cover"]
            if (
                research_envelope.payload is None
                or download_envelope.payload is None
                or content_envelope.payload is None
                or cover_envelope.payload is None
            ):
                return ResultEnvelope[DeliveryPackage].error(
                    agent_name="review_delivery_agent",
                    summary="视频交付输入为空，无法生成飞书交付包",
                    error_message="video delivery inputs are empty",
                    run_id=kwargs["run_id"],
                    step_id="delivery",
                    artifacts=[
                        *download_envelope.artifacts,
                        *cover_envelope.artifacts,
                    ],
                )
            package = _build_video_delivery_package(
                brief=brief,
                research=research_envelope.payload,
                download=download_envelope.payload,
                content=content_envelope.payload,
                cover=cover_envelope.payload,
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

        runner = VideoWorkflowRunner(
            deps=VideoWorkflowDeps(
                run_research=run_research,
                run_download=run_download,
                run_content=run_content,
                run_cover=run_cover,
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
        )

        if send_to_feishu and self.delivery_sender is not None:
            await self.delivery_sender.send(envelope, chat_id=chat_id)

        return envelope
