from __future__ import annotations

from typing import Any

from src.orchestration.conversation import ContentRoute, ConversationRequest
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
            )
        )
    if article_runner is not None:
        registry.register(
            AgentTool(
                name="execute_article_post",
                description="Execute an article-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(article_runner, ContentRoute.ARTICLE_POST),
            )
        )
    if video_runner is not None:
        registry.register(
            AgentTool(
                name="execute_video_post",
                description="Execute a video-post specialist workflow from a TaskRunSpec.",
                execute=_build_route_execute(video_runner, ContentRoute.VIDEO_POST),
            )
        )
    return registry


def _build_route_execute(runner: Any, route: ContentRoute):
    async def execute(
        ctx: AgentToolContext,
        *,
        spec: dict[str, Any],
    ) -> AgentToolResult:
        task_spec = TaskRunSpec.model_validate(spec)
        request = conversation_request_from_task_spec(
            task_spec.model_copy(update={"route": route})
        )
        envelope: ResultEnvelope[DeliveryPackage] = await runner.run(
            request,
            run_id=ctx.run_id,
            chat_id=ctx.chat_id,
            send_to_feishu=True,
            run_options=task_spec.run_options,
        )
        return AgentToolResult(envelope=envelope, produced_refs=[route.value])

    return execute
