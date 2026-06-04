from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import mimetypes
import inspect
import re
from typing import Any

from src.agents.image_post.content.agent import ContentAgent
from src.agents.image_post.image.agent import ImageAgent
from src.agents.image_post.research.agent import ResearchAgent
from src.agents.image_post.schemas import GroupSpec, ImageResult, ResearchResult, XHSContent
from src.agents.image_post.utils.research import sanitize_research_for_content
from src.agents.shared.login import AuthResult
from src.config.settings import PathConfig

from .conversation import ConversationRequest
from .image_flow import ImageWorkflowDeps, ImageWorkflowRunner, image_workflow_module_graph
from .request_brief import RequestBrief, build_request_brief
from .run_options import ImagePostRunOptions
from .schemas import (
    ArtifactRef,
    DeliveryPackage,
    DeliveryTextBlock,
    GroupingItem,
    GroupingResult,
    ResultEnvelope,
    WorkflowInvocation,
)
from .style_context import StyleContext
from .workspace import WorkflowWorkspace


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str, *, max_length: int = 24) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value).strip("-")
    return (cleaned or "run")[:max_length]


def _guess_mime_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _grouping_payload_to_specs(payload: GroupingResult) -> list[GroupSpec]:
    return [{"title": group.title, "indices": list(group.indices)} for group in payload.groups]


def _build_image_delivery_package(
    *,
    brief: RequestBrief,
    research: ResultEnvelope[ResearchResult],
    groups: ResultEnvelope[GroupingResult],
    content: ResultEnvelope[XHSContent],
    images: list[ResultEnvelope[ImageResult]],
    style_context: StyleContext | None = None,
    run_options: ImagePostRunOptions | None = None,
) -> DeliveryPackage:
    content_payload = content.payload
    research_payload = research.payload
    groups_payload = groups.payload or GroupingResult()
    image_artifacts: list[ArtifactRef] = []
    for image_envelope in images:
        image_artifacts.extend(image_envelope.artifacts)
    actual_image_count = len(image_artifacts)

    group_titles = "、".join(group.title for group in groups_payload.groups) or "未分组"
    hashtags = ""
    if content_payload is not None and content_payload.hashtags:
        hashtags = " ".join(f"#{tag}" for tag in content_payload.hashtags)

    text_blocks = [
        DeliveryTextBlock(label="topic", text=f"主题：{brief.topic}"),
        DeliveryTextBlock(label="audience", text=f"受众：{brief.audience}"),
        DeliveryTextBlock(label="requirements", text=brief.requirements_text),
        DeliveryTextBlock(label="title", text=f"标题：{content_payload.title if content_payload else brief.topic}"),
        DeliveryTextBlock(label="body", text=f"正文：{content_payload.body if content_payload else ''}"),
        DeliveryTextBlock(label="hashtags", text=f"话题：{hashtags or '无'}"),
        DeliveryTextBlock(label="research_summary", text=f"调研摘要：{research_payload.summary if research_payload else ''}"),
        DeliveryTextBlock(label="group_summary", text=f"分组：{group_titles}"),
    ]

    return DeliveryPackage(
        route="image_post",
        title=content_payload.title if content_payload is not None else brief.topic,
        summary=f"{brief.topic} 的飞书交付包已整理完成",
        text_blocks=text_blocks,
        artifacts=image_artifacts,
        metadata={
            "topic": brief.topic,
            "audience": brief.audience,
            "group_count": len(groups_payload.groups),
            "image_count": actual_image_count,
            "requested_image_count": brief.image_count,
            "single_item_per_image": brief.single_item_per_image,
            "style_constraints": list(brief.style_constraints),
            "style_context": style_context.metadata() if style_context is not None else {},
            "run_options": run_options.model_dump(mode="json") if run_options is not None else {},
            "workflow_graph": {
                "name": image_workflow_module_graph.name,
                "modules": image_workflow_module_graph.describe(),
            },
        },
    )


def _build_research_access_envelope(
    *,
    payload: AuthResult,
    run_id: str,
) -> ResultEnvelope[AuthResult]:
    summary = payload.message or "研究前登录预检完成"
    if payload.success:
        return ResultEnvelope[AuthResult].success(
            agent_name="research_access_agent",
            payload=payload,
            summary=summary,
            run_id=run_id,
            step_id="research_access",
        )

    return ResultEnvelope[AuthResult].error(
        agent_name="research_access_agent",
        summary=f"登录预检失败：{summary}",
        error_message=summary,
        run_id=run_id,
        step_id="research_access",
    )


class ImagePostOrchestrator:
    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        delivery_sender: Any | None = None,
        research_agent_factory: type[ResearchAgent] = ResearchAgent,
        content_agent_factory: type[ContentAgent] = ContentAgent,
        image_agent_factory: type[ImageAgent] = ImageAgent,
        run_options: ImagePostRunOptions | None = None,
    ) -> None:
        self.workspace_root = workspace_root or PathConfig.ORCHESTRATION_RUN_DIR
        self.delivery_sender = delivery_sender
        self.research_agent_factory = research_agent_factory
        self.content_agent_factory = content_agent_factory
        self.image_agent_factory = image_agent_factory
        self.run_options = run_options or ImagePostRunOptions()

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
        run_options: ImagePostRunOptions | None = None,
    ) -> ResultEnvelope[DeliveryPackage]:
        brief = build_request_brief(request)
        style_context = style_context or StyleContext.from_request(request)
        resolved_run_options = run_options or self.run_options or ImagePostRunOptions()
        resolved_run_id = run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_slug(brief.topic)}"
        workspace = WorkflowWorkspace.create(
            root_dir=self.workspace_root,
            run_id=resolved_run_id,
            route="image_post",
            topic=brief.topic,
            audience=brief.audience,
        )
        research_agent = self._instantiate_agent(
            self.research_agent_factory,
            run_options=resolved_run_options.research,
        )
        content_agent = self.content_agent_factory()
        image_agent = self._instantiate_agent(
            self.image_agent_factory,
            run_options=resolved_run_options.image,
        )
        reference_artifacts = [
            ArtifactRef(
                artifact_type="image",
                label=f"reference_{index + 1}",
                path=path,
                mime_type=_guess_mime_type(path),
                metadata={"source": "conversation_request"},
            )
            for index, path in enumerate(request.reference_images)
        ]
        workflow_invocation = WorkflowInvocation(
            objective=request.message or brief.execution_text,
            route="image_post",
            topic=brief.topic,
            audience=brief.audience,
            selected_skills=list(style_context.matched_skills),
            selected_prompt_templates=[ref.source for ref in style_context.prompt_refs],
            user_requirements=[brief.requirements_text],
            constraints=[
                *brief.style_constraints,
                *style_context.hard_constraints,
                *style_context.negative_constraints,
            ],
            artifacts=reference_artifacts,
            run_options=resolved_run_options.model_dump(mode="json"),
            delivery={"target": "feishu", "chat_id": chat_id},
        )
        workspace.save_invocation(workflow_invocation)

        async def run_research(
            *,
            topic: str,
            audience: str,
            execution_text: str,
            run_id: str,
            workspace_dir: Path,
        ) -> ResultEnvelope[ResearchResult]:
            payload = await research_agent.forward(
                topic=execution_text,
                target_audience=audience,
                output_dir=workspace_dir,
            )
            payload = sanitize_research_for_content(payload)
            envelope = ResultEnvelope[ResearchResult].success(
                agent_name="research_agent",
                payload=payload,
                summary=payload.summary or f"{topic} 调研完成",
                run_id=run_id,
                step_id="research",
            )
            workspace.save_envelope(envelope, label="research")
            return envelope

        async def run_grouping(
            *,
            topic: str,
            execution_text: str,
            research: ResultEnvelope[ResearchResult],
            run_id: str,
            workspace_dir: Path,
        ) -> ResultEnvelope[GroupingResult]:
            if research.payload is None:
                return ResultEnvelope[GroupingResult].error(
                    agent_name="grouping_agent",
                    summary="研究结果为空，无法分组",
                    error_message="research payload is empty",
                    run_id=run_id,
                    step_id="grouping",
                )
            groups = await image_agent.compute_groups(
                research.payload,
                execution_text,
                requested_image_count=brief.image_count,
                single_item_per_image=brief.single_item_per_image,
            )
            payload = GroupingResult(
                groups=[
                    GroupingItem(title=str(group["title"]), indices=list(group["indices"]))
                    for group in groups
                ]
            )
            envelope = ResultEnvelope[GroupingResult].success(
                agent_name="grouping_agent",
                payload=payload,
                summary=f"完成 {len(payload.groups)} 个语义分组",
                run_id=run_id,
                step_id="grouping",
            )
            workspace.save_envelope(envelope, label="grouping")
            return envelope

        async def run_content(
            *,
            topic: str,
            execution_text: str,
            research: ResultEnvelope[ResearchResult],
            groups: ResultEnvelope[GroupingResult],
            run_id: str,
            workspace_dir: Path,
        ) -> ResultEnvelope[XHSContent]:
            if research.payload is None or groups.payload is None:
                return ResultEnvelope[XHSContent].error(
                    agent_name="content_agent",
                    summary="研究或分组结果为空，无法生成内容",
                    error_message="missing research or grouping payload",
                    run_id=run_id,
                    step_id="content",
                )
            payload = await content_agent.forward(
                research=research.payload,
                topic=execution_text,
                groups=_grouping_payload_to_specs(groups.payload),
            )
            envelope = ResultEnvelope[XHSContent].success(
                agent_name="content_agent",
                payload=payload,
                summary=f"内容生成完成：{payload.title}",
                run_id=run_id,
                step_id="content",
            )
            workspace.save_envelope(envelope, label="content")
            return envelope

        async def run_image_group(
            *,
            topic: str,
            execution_text: str,
            group: dict[str, object],
            group_index: int,
            research: ResultEnvelope[ResearchResult],
            content: ResultEnvelope[XHSContent],
            run_id: str,
            workspace_dir: Path,
            image_task: Any | None = None,
        ) -> ResultEnvelope[ImageResult]:
            if research.payload is None or content.payload is None:
                return ResultEnvelope[ImageResult].error(
                    agent_name="image_generation_agent",
                    summary="研究或内容为空，无法生成图片",
                    error_message="missing research or content payload",
                    run_id=run_id,
                    step_id=f"image-{group_index}",
                )
            image_type = str(group.get("image_type") or f"detail_{group_index}")
            image_spec: dict[str, object] = {
                "type": image_type,
                "desc": str(
                    group.get("desc")
                    or (
                        "封面图 - 纯视觉主图，突出主题；除非用户明确要求文字海报，否则不要生成标题文字"
                        if image_type == "cover"
                        else f"详情图 - 语义分组：{group.get('title', '')}"
                    )
                ),
            }
            image_spec["group_title"] = str(group.get("title") or "")
            image_spec["indices"] = list(group.get("indices") or [])

            generated = await image_agent.step(
                content=content.payload,
                research=research.payload,
                topic=execution_text,
                output_dir=workspace_dir,
                image_spec=image_spec,
                style_context=style_context,
            )
            image_artifact = ArtifactRef(
                artifact_type="image",
                label=image_type,
                path=generated.image_path,
                mime_type=_guess_mime_type(generated.image_path),
                metadata={
                    "group_title": str(group.get("title") or ""),
                    "style_context": style_context.metadata(),
                    "image_task": image_task.model_dump(mode="json") if image_task is not None else {},
                    "prompt_summary": generated.prompt_used[:500],
                },
            )
            payload = ImageResult(
                images=[generated],
                total_count=1,
                generated_at=_utc_iso(),
            )
            envelope = ResultEnvelope[ImageResult].success(
                agent_name="image_generation_agent",
                payload=payload,
                summary=f"图片生成完成：{image_type}",
                run_id=run_id,
                step_id=f"image-{group_index}",
                artifacts=[image_artifact],
            )
            workspace.save_envelope(envelope, label=f"image-{group_index}")
            return envelope

        async def run_delivery(
            *,
            topic: str,
            execution_text: str,
            research: ResultEnvelope[ResearchResult],
            groups: ResultEnvelope[GroupingResult],
            content: ResultEnvelope[XHSContent],
            images: list[ResultEnvelope[ImageResult]],
            run_id: str,
            workspace_dir: Path,
        ) -> ResultEnvelope[DeliveryPackage]:
            package = _build_image_delivery_package(
                brief=brief,
                research=research,
                groups=groups,
                content=content,
                images=images,
                style_context=style_context,
                run_options=resolved_run_options,
            )
            envelope = ResultEnvelope[DeliveryPackage].success(
                agent_name="review_delivery_agent",
                payload=package,
                summary=package.summary,
                run_id=run_id,
                step_id="delivery",
                artifacts=package.artifacts,
            )
            workspace.save_envelope(envelope, label="delivery")
            return envelope

        runner = ImageWorkflowRunner(
            deps=ImageWorkflowDeps(
                run_research=run_research,
                run_grouping=run_grouping,
                run_content=run_content,
                run_image_group=run_image_group,
                run_delivery=run_delivery,
            )
        )

        prepare_research_access = getattr(research_agent, "prepare_research_access", None)
        if callable(prepare_research_access):
            access_result = await prepare_research_access()
            access_envelope = _build_research_access_envelope(
                payload=access_result,
                run_id=resolved_run_id,
            )
            workspace.save_envelope(access_envelope, label="research_access")
            if access_envelope.status == "error":
                return ResultEnvelope[DeliveryPackage].error(
                    agent_name="review_delivery_agent",
                    summary=access_envelope.summary,
                    error_message=access_envelope.error_message or access_envelope.summary,
                    run_id=resolved_run_id,
                    step_id="research_access",
                )

        try:
            result = await runner.run(
                topic=brief.topic,
                audience=brief.audience,
                run_id=resolved_run_id,
                workspace_dir=workspace.run_dir,
                execution_text=brief.execution_text,
                invocation=workflow_invocation,
                image_count=brief.image_count,
                single_item_per_image=brief.single_item_per_image,
                max_auto_images=resolved_run_options.max_auto_images,
                image_generation_concurrency=resolved_run_options.image_generation_concurrency,
            )
        except Exception as exc:
            result = ResultEnvelope[DeliveryPackage].error(
                agent_name="feishu_image_post_orchestrator",
                summary=f"image_post 工作流失败：{exc}",
                error_message=str(exc),
                run_id=resolved_run_id,
                step_id="workflow",
            )
            workspace.save_envelope(result, label="workflow-error")

        if send_to_feishu and self.delivery_sender is not None and result.status == "success":
            await self.delivery_sender.send(result, chat_id=chat_id)

        return result
