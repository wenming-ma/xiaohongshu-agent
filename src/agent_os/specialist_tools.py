from __future__ import annotations

from typing import Any

from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.run_options import (
    ArticlePostRunOptions,
    ArticleResearchRunOptions,
    ImagePostRunOptions,
    ImageRunOptions,
    ResearchRunOptions,
)
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope

from .schemas import AgentToolResult, TaskRunSpec
from .tools import AgentTool, AgentToolContext, AgentToolRegistry


def conversation_request_from_task_spec(spec: TaskRunSpec) -> ConversationRequest:
    reference_images = [ref.path for ref in spec.reference_images]
    return ConversationRequest(
        topic=spec.topic or spec.objective,
        audience=spec.audience or "泛人群",
        message=spec.objective,
        route_hint=spec.route,
        style_constraints=list(spec.style_constraints),
        image_count=spec.run_options.image.count,
        reference_images=reference_images,
    )


def build_route_tool_registry(
    *,
    image_runner: Any | None = None,
    article_runner: Any | None = None,
    video_runner: Any | None = None,
) -> AgentToolRegistry:
    registry = AgentToolRegistry()
    if image_runner is not None:
        registry.register(
            AgentTool(
                name="execute_image_post",
                description="Execute an image-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(image_runner, ContentRoute.IMAGE_POST),
                resource_group="browser_research",
            )
        )
    if article_runner is not None:
        registry.register(
            AgentTool(
                name="execute_article_post",
                description="Execute an article-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(article_runner, ContentRoute.ARTICLE_POST),
                resource_group="browser_research",
            )
        )
    if video_runner is not None:
        registry.register(
            AgentTool(
                name="execute_video_post",
                description="Execute a video-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(video_runner, ContentRoute.VIDEO_POST),
                resource_group="browser_research",
            )
        )
    return registry


def _build_route_execute(runner: Any, route: ContentRoute):
    async def execute(
        ctx: AgentToolContext,
        *,
        spec: dict[str, Any],
        **extra_context: Any,
    ) -> AgentToolResult:
        task_spec = TaskRunSpec.model_validate(_merge_route_extra_context(spec, extra_context))
        request = conversation_request_from_task_spec(
            task_spec.model_copy(update={"route": route})
        )
        envelope: ResultEnvelope[DeliveryPackage] = await runner.run(
            request,
            run_id=ctx.run_id,
            chat_id=ctx.chat_id,
            send_to_feishu=True,
            run_options=_route_run_options_from_task_spec(task_spec, route),
        )
        return AgentToolResult(envelope=envelope, produced_refs=[route.value])

    return execute


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
        if task_spec.run_options.image.size:
            image_updates["image_size"] = task_spec.run_options.image.size
        if task_spec.run_options.image.aspect_ratio:
            image_updates["aspect_ratio"] = task_spec.run_options.image.aspect_ratio
        if task_spec.run_options.image.reference_mode:
            image_updates["reference_mode"] = task_spec.run_options.image.reference_mode

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

    return None


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
