from __future__ import annotations

import os
from typing import Literal

from .feishu_notifier import FeishuNotifier
from .feishu_sessions import (
    FeishuWorkflowSession,
    get_feishu_session_manager,
    wait_for_session_activation,
)


async def acquire_interactive_session(
    *,
    notifier: FeishuNotifier,
    workflow: str,
    summary: str,
    current_phase: str = "startup",
    takeover_timeout_seconds: int = 5 * 60,
) -> tuple[FeishuWorkflowSession | None, str | None]:
    if notifier.client is None or not notifier.chat_id:
        return None, None

    manager = get_feishu_session_manager()
    result = manager.acquire(
        chat_id=notifier.chat_id,
        workflow=workflow,
        owner_pid=os.getpid(),
        current_phase=current_phase,
        summary=summary,
    )

    if result.outcome == "acquired":
        session = FeishuWorkflowSession(
            manager,
            result.session,
            current_phase=current_phase,
            summary=summary,
        )
        await session.start()
        return session, None

    if result.reason == "challenger_pending":
        return None, "blocked_pending_takeover"

    await notifier.send_takeover_control_card(
        chat_id=notifier.chat_id,
        workflow=workflow,
        challenger_session_id=result.session.session_id,
        active_workflow=result.state.workflow,
        active_phase=result.state.current_phase,
        active_summary=result.state.summary,
        active_started_at=result.state.started_at,
        active_heartbeat_at=result.state.heartbeat_at,
    )

    wait_result = await wait_for_session_activation(
        manager,
        result.session,
        timeout_seconds=takeover_timeout_seconds,
    )
    if wait_result.outcome == "acquired":
        session = FeishuWorkflowSession(
            manager,
            result.session,
            current_phase=current_phase,
            summary=summary,
        )
        await session.start()
        return session, None

    manager.release(result.session, status="cancelled")
    return None, f"blocked_{wait_result.outcome}"


async def finalize_interactive_session(
    session: FeishuWorkflowSession | None,
    *,
    status: Literal["completed", "cancelled"],
) -> None:
    if session is None:
        return
    await session.finish(status=status)
