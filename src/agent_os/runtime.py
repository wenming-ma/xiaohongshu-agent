from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Protocol

from .schemas import AgentOSEvent, EventPriority


class SupportsMainAgentRun(Protocol):
    def enqueue(self, text: str, *, priority: str = "asap") -> None: ...


class PydanticAgentRunAdapter:
    def __init__(self, agent_run: Any) -> None:
        self.agent_run = agent_run
        self.cancelled = False

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.agent_run.enqueue(text, priority=priority)

    def reset_session(self) -> None:
        self.cancel_current_task()

    def cancel_current_task(self) -> None:
        self.cancelled = True
        cancel = getattr(self.agent_run, "cancel", None)
        if callable(cancel):
            cancel()


class MainAgentRuntime:
    def __init__(self) -> None:
        self._run: SupportsMainAgentRun | None = None
        self._pending: deque[AgentOSEvent] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def attach_run(self, run: SupportsMainAgentRun) -> None:
        self._run = run
        self.flush()

    def detach_run(self, run: SupportsMainAgentRun | None = None) -> None:
        if run is None or run is self._run:
            self._run = None

    def ingest_event(self, event: AgentOSEvent) -> None:
        action = self._control_action(event)
        if action == "new_session":
            self._pending.clear()
            self.reset_session()
            return
        if action == "interrupt":
            self.cancel_current_task()
            self._enqueue_text("[用户控制事件]\naction: interrupt", priority="asap")
            return
        if action == "follow_up":
            self._enqueue_text("[用户控制事件]\naction: follow_up", priority="when_idle")
            return

        if self._run is None:
            self._pending.append(event)
            return
        self._enqueue_event(event)

    def ingest_text(self, text: str, *, priority: EventPriority = "asap") -> None:
        self.ingest_event(AgentOSEvent.text(text, priority=priority))

    def ingest_event_from_image(
        self,
        image_path: Path,
        *,
        caption: str = "",
        priority: EventPriority = "asap",
    ) -> None:
        self.ingest_event(
            AgentOSEvent.image(str(image_path), caption=caption, priority=priority)
        )

    def flush(self) -> None:
        while self._run is not None and self._pending:
            self._enqueue_event(self._pending.popleft())

    async def wait_for_idle(self) -> None:
        wait_for_idle = getattr(self._run, "wait_for_idle", None)
        if callable(wait_for_idle):
            await wait_for_idle()

    def reset_session(self) -> None:
        reset = getattr(self._run, "reset_session", None)
        if callable(reset):
            reset()

    def cancel_current_task(self) -> None:
        cancel = getattr(self._run, "cancel_current_task", None)
        if callable(cancel):
            cancel()

    def _enqueue_event(self, event: AgentOSEvent) -> None:
        if event.kind == "image" and event.image_path:
            self._enqueue_text(self._format_image_message(event), priority=event.priority)
            return
        self._enqueue_text(event.text, priority=event.priority)

    def _enqueue_text(self, text: str, *, priority: EventPriority) -> None:
        if self._run is None:
            self._pending.append(AgentOSEvent.text(text, priority=priority))
            return
        self._run.enqueue(text, priority=priority)

    def _format_image_message(self, event: AgentOSEvent) -> str:
        parts = ["[用户发送图片]", f"path: {event.image_path}"]
        if event.text.strip():
            parts.append(f"caption: {event.text.strip()}")
        return "\n".join(parts)

    def _control_action(self, event: AgentOSEvent) -> str:
        if event.kind != "control":
            return ""
        action = str(event.payload.get("action") or event.text).strip()
        return action if action in {"new_session", "interrupt", "follow_up"} else ""
