from __future__ import annotations

import inspect
import mimetypes
from typing import Any

from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.run_options import (
    ArticlePostRunOptions,
    ArticleResearchRunOptions,
    ImagePostRunOptions,
    ImageRunOptions,
    ResearchRunOptions,
    VideoPostRunOptions,
    VideoResearchRunOptions,
)
from src.orchestration.schemas import ArtifactRef, DeliveryPackage, ResultEnvelope, WorkflowInvocation

from .reference_assets import ReferenceAssetBatch, ReferenceAssetStore
from .schemas import AgentToolResult, TaskRunSpec
from .tools import AgentTool, AgentToolContext, AgentToolRegistry


def conversation_request_from_task_spec(spec: TaskRunSpec) -> ConversationRequest:
    reference_images = [ref.path for ref in spec.reference_images]
    message_parts = [
        part
        for part in [spec.objective, *spec.user_requirements]
        if str(part or "").strip()
    ]
    return ConversationRequest(
        topic=spec.topic or spec.objective,
        audience=spec.audience or "泛人群",
        message="\n\n".join(dict.fromkeys(message_parts)),
        route_hint=spec.route,
        style_constraints=list(spec.style_constraints),
        image_count=spec.run_options.image.count,
        reference_images=reference_images,
    )


def workflow_invocation_from_task_spec(spec: TaskRunSpec) -> WorkflowInvocation:
    """Normalize an Agent OS task spec into the graph-level invocation contract."""

    return WorkflowInvocation.from_task_spec(spec)


def build_route_tool_registry(
    *,
    image_runner: Any | None = None,
    article_runner: Any | None = None,
    video_runner: Any | None = None,
    reference_asset_store: ReferenceAssetStore | None = None,
) -> AgentToolRegistry:
    registry = AgentToolRegistry()
    if image_runner is not None:
        registry.register(
            AgentTool(
                name="execute_image_post",
                description="Execute an image-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(
                    image_runner,
                    ContentRoute.IMAGE_POST,
                    reference_asset_store=reference_asset_store,
                ),
                resource_group="browser_research",
            )
        )
    if article_runner is not None:
        registry.register(
            AgentTool(
                name="execute_article_post",
                description="Execute an article-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(
                    article_runner,
                    ContentRoute.ARTICLE_POST,
                    reference_asset_store=reference_asset_store,
                ),
                resource_group="browser_research",
            )
        )
    if video_runner is not None:
        registry.register(
            AgentTool(
                name="execute_video_post",
                description="Execute a video-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(
                    video_runner,
                    ContentRoute.VIDEO_POST,
                    reference_asset_store=reference_asset_store,
                ),
                resource_group="browser_research",
            )
        )
    return registry


def _build_route_execute(
    runner: Any,
    route: ContentRoute,
    *,
    reference_asset_store: ReferenceAssetStore | None = None,
):
    async def execute(
        ctx: AgentToolContext,
        *,
        spec: dict[str, Any],
        **extra_context: Any,
    ) -> AgentToolResult:
        task_spec = TaskRunSpec.model_validate(_merge_route_extra_context(spec, extra_context))
        task_spec = _expand_reference_asset_batches(task_spec, reference_asset_store=reference_asset_store)
        workflow_invocation = workflow_invocation_from_task_spec(task_spec)
        request = conversation_request_from_task_spec(
            task_spec.model_copy(update={"route": route})
        )
        runner_kwargs: dict[str, Any] = {
            "run_id": ctx.run_id,
            "chat_id": ctx.chat_id,
            "send_to_feishu": True,
            "run_options": _route_run_options_from_task_spec(task_spec, route),
        }
        if _callable_accepts_param(runner.run, "workflow_invocation"):
            runner_kwargs["workflow_invocation"] = workflow_invocation
        envelope: ResultEnvelope[DeliveryPackage] = await runner.run(request, **runner_kwargs)
        return AgentToolResult(envelope=envelope, produced_refs=[route.value])

    return execute


def _expand_reference_asset_batches(
    task_spec: TaskRunSpec,
    *,
    reference_asset_store: ReferenceAssetStore | None,
) -> TaskRunSpec:
    if not task_spec.reference_asset_batch_ids:
        return task_spec
    if reference_asset_store is None:
        raise ValueError("reference_asset_batch_ids require a ReferenceAssetStore")

    artifacts = list(task_spec.reference_images)
    for batch_id in task_spec.reference_asset_batch_ids:
        batch = reference_asset_store.get_batch(batch_id)
        artifacts.extend(_artifact_refs_from_reference_batch(batch))
    return task_spec.model_copy(update={"reference_images": artifacts})


def _artifact_refs_from_reference_batch(batch: ReferenceAssetBatch) -> list[ArtifactRef]:
    return [
        ArtifactRef(
            artifact_type="image",
            label=image.label,
            path=image.path,
            mime_type=_guess_mime_type(image.path),
            metadata={
                "description": image.description,
                "instruction": batch.instruction,
                "reference_role": image.use_as,
            },
        )
        for image in batch.images
    ]


def _route_run_options_from_task_spec(task_spec: TaskRunSpec, route: ContentRoute) -> Any:
    if route == ContentRoute.IMAGE_POST:
        research_updates: dict[str, Any] = {}
        if task_spec.run_options.research.max_items is not None:
            research_budget = task_spec.run_options.research.max_items
            research_updates.update(
                {
                    "min_posts_researched": research_budget,
                    "validation_max_retries": research_budget,
                    "min_key_infos": research_budget,
                    "min_cases": research_budget,
                    "max_new_posts_per_iteration": research_budget,
                }
            )

        image_updates: dict[str, Any] = {}
        if task_spec.run_options.image.model:
            image_updates["model"] = task_spec.run_options.image.model
        if task_spec.run_options.image.size:
            image_updates["image_size"] = task_spec.run_options.image.size
        if task_spec.run_options.image.aspect_ratio:
            image_updates["aspect_ratio"] = task_spec.run_options.image.aspect_ratio
        if task_spec.run_options.image.reference_mode:
            image_updates["reference_mode"] = _normalize_image_reference_mode(
                task_spec.run_options.image.reference_mode
            )

        route_updates: dict[str, Any] = {}
        if task_spec.run_options.image.concurrency is not None:
            route_updates["image_generation_concurrency"] = task_spec.run_options.image.concurrency

        return ImagePostRunOptions(
            research=ResearchRunOptions(**research_updates),
            image=ImageRunOptions(**image_updates),
            **route_updates,
        )

    if route == ContentRoute.ARTICLE_POST:
        research_updates: dict[str, Any] = {}
        if task_spec.run_options.research.max_items is not None:
            research_budget = task_spec.run_options.research.max_items
            research_updates.update(
                {
                    "min_source_pages": research_budget,
                    "min_unique_domains": research_budget,
                    "max_source_pages": research_budget,
                    "max_iterations": research_budget,
                    "max_tasks_per_iteration": research_budget,
                    "max_curated_sources_per_task": research_budget,
                    "max_curated_video_sources_per_task": research_budget,
                    "min_curated_sources_for_note_compression": research_budget,
                    "min_digests_for_full_synthesis": research_budget,
                }
            )
        return ArticlePostRunOptions(research=ArticleResearchRunOptions(**research_updates))

    if route == ContentRoute.VIDEO_POST:
        research_updates: dict[str, Any] = {}
        if task_spec.run_options.research.max_items is not None:
            research_budget = task_spec.run_options.research.max_items
            research_updates.update(
                {
                    "max_iterations": research_budget,
                    "max_videos": research_budget,
                    "min_quality_videos": research_budget,
                }
            )
        return VideoPostRunOptions(research=VideoResearchRunOptions(**research_updates))

    return None


def _normalize_image_reference_mode(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"none", "off", "disabled", "no_reference", "text_to_image"}:
        return "none"
    if normalized in {
        "gemini_content",
        "reference_image",
        "reference_images",
        "style_reference",
        "object_transfer",
        "subject_reference",
        "composition_reference",
        "scene_reference",
        "material_color_reference",
        "unspecified",
    }:
        return "gemini_content"
    return value


def _guess_mime_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or ""


def _merge_route_extra_context(
    spec: dict[str, Any],
    extra_context: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(spec)
    skill = extra_context.get("skill") or extra_context.get("selected_skill")
    if skill:
        selected_skills = list(merged.get("selected_skills") or [])
        selected_skills.append(str(skill))
        merged["selected_skills"] = selected_skills

    prompt_template = (
        extra_context.get("prompt_template")
        or extra_context.get("template")
        or extra_context.get("selected_prompt_template")
    )
    if prompt_template:
        selected_prompt_templates = list(merged.get("selected_prompt_templates") or [])
        selected_prompt_templates.append(str(prompt_template))
        merged["selected_prompt_templates"] = selected_prompt_templates

    return merged


def _callable_accepts_param(func: Any, param_name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    return param_name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
