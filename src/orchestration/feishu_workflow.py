from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from src.utils.feishu_interactive_workflow import acquire_interactive_session, finalize_interactive_session
from src.utils.feishu_notifier import FeishuNotifier, get_feishu_notifier
from src.utils.logger import get_logger

from .controller import FeishuContentOrchestrator
from .conversation import ContentRoute, ConversationRequest
from .feishu_interactions import FeishuInteractionTools, FeishuSessionResetRequested
from .feishu_translation import parse_control_action_text
from .request_parser import parse_conversation_request

logger = get_logger(__name__)


AcquireSessionFn = Callable[..., Awaitable[tuple[object | None, str | None]]]


class FeishuWorkflowService:
    def __init__(
        self,
        *,
        notifier: FeishuNotifier | None = None,
        orchestrator: FeishuContentOrchestrator | None = None,
        acquire_session: AcquireSessionFn | None = None,
        interaction_tools: FeishuInteractionTools | None = None,
    ) -> None:
        self.notifier = notifier or get_feishu_notifier()
        self.orchestrator = orchestrator or FeishuContentOrchestrator()
        self.acquire_session = acquire_session or self._default_acquire_session
        self.interaction_tools = interaction_tools or FeishuInteractionTools(
            notifier=self.notifier,
            route_resolver=self._resolve_route_for_interactions,
        )

    async def serve_forever(self) -> None:
        await self.notifier.start_polling()
        logger.info("FeishuWorkflowService 已启动，等待文本或参考图请求…")
        while True:
            try:
                image_path, text = await self.notifier.wait_for_image_or_text()
                if image_path is not None:
                    await self.handle_reference_image(image_path)
                    continue
                if not text.strip():
                    continue
                await self.handle_text(text)
            except Exception:
                logger.exception("处理飞书请求失败")
                await self.interaction_tools.send_runtime_error()

    async def handle_text(self, text: str) -> None:
        if self._is_new_session_control(text):
            await self.interaction_tools.announce_session_reset()
            return
        request = parse_conversation_request(text)
        await self._handle_request(request)

    async def handle_reference_image(self, image_path: Path) -> None:
        session, blocked_reason = await self.acquire_session(
            workflow="feishu_orchestrator",
            summary="参考图请求",
        )
        if blocked_reason:
            await self.interaction_tools.send_busy(blocked_reason)
            return
        if session is None:
            await self.interaction_tools.send_session_unavailable()
            return

        session_status = "cancelled"
        try:
            request = await self.interaction_tools.collect_reference_image_request(session, image_path)
            if request is None:
                return
            await self._handle_request(request, session=session)
            session = None
            session_status = "completed"
        finally:
            if session is not None:
                await finalize_interactive_session(session, status=session_status)

    async def _handle_request(self, request: ConversationRequest, *, session: object | None = None) -> None:
        session, blocked_reason = await self.acquire_session(
            workflow="feishu_orchestrator",
            summary=request.topic,
        ) if session is None else (session, None)
        if blocked_reason:
            await self.interaction_tools.send_busy(blocked_reason)
            return
        if session is None:
            await self.interaction_tools.send_session_unavailable()
            return

        session_status = "cancelled"
        try:
            request = await self.interaction_tools.clarify_request_if_needed(session, request)
            await self._update_session_phase(session, "planning", summary=request.topic)
            prepare_request = getattr(self.orchestrator, "prepare_request", None)
            if callable(prepare_request):
                request = prepare_request(request)
            planner = getattr(self.orchestrator, "planner", None)
            plan = await planner.plan(request) if planner is not None else None
            route_label = plan.route.value if plan is not None else (request.route_hint.value if request.route_hint else "auto")
            await self.interaction_tools.announce_execution_started(session, request, route_label=route_label)
            await self._update_session_phase(session, f"running_{route_label}", summary=request.topic)
            result = await self.orchestrator.run_request(
                request,
                chat_id=session.chat_id,
                run_id=self._build_run_id(route_label),
                send_to_feishu=True,
            )
            session_status = "completed" if result.status == "success" else "cancelled"
            await self.interaction_tools.announce_delivery_result(session, result)
        except FeishuSessionResetRequested:
            session_status = "cancelled"
            await self.interaction_tools.announce_session_reset(session)
            return
        finally:
            if session is not None:
                await finalize_interactive_session(session, status=session_status)

    async def _default_acquire_session(self, *, workflow: str, summary: str):
        return await acquire_interactive_session(
            notifier=self.notifier,
            workflow=workflow,
            summary=summary,
            current_phase="startup",
        )

    async def _update_session_phase(self, session: object, phase: str, *, summary: str | None = None) -> None:
        update_phase = getattr(session, "update_phase", None)
        if callable(update_phase):
            await update_phase(phase, summary=summary)

    def _build_run_id(self, route: str) -> str:
        return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{route}"

    def _is_new_session_control(self, text: str) -> bool:
        return parse_control_action_text(text) == "new_session"

    async def _resolve_route_for_interactions(self, request: ConversationRequest) -> ContentRoute:
        planner = getattr(self.orchestrator, "planner", None)
        if planner is not None:
            return (await planner.plan(request)).route
        return request.route_hint or ContentRoute.IMAGE_POST
