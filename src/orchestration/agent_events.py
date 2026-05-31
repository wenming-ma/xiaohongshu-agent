from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


EnqueuePriority = Literal["asap", "when_idle"]
ControlAction = Literal["new_session", "interrupt", "follow_up"]


class SupportsAgentEnqueue(Protocol):
    def enqueue(self, *items: Any, priority: EnqueuePriority = "asap") -> None: ...


@dataclass(frozen=True)
class QueuedAgentEvent:
    text: str
    priority: EnqueuePriority = "asap"


class AgentEventBridge:
    """Owns external user-event insertion for a long-running Pydantic AI run."""

    def __init__(self) -> None:
        self._agent_run: SupportsAgentEnqueue | None = None
        self._pending: deque[QueuedAgentEvent] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def attach_run(self, agent_run: SupportsAgentEnqueue) -> None:
        self._agent_run = agent_run
        self.flush()

    def detach_run(self, agent_run: SupportsAgentEnqueue | None = None) -> None:
        if agent_run is None or agent_run is self._agent_run:
            self._agent_run = None

    def ingest_user_text(self, text: str, *, priority: EnqueuePriority = "asap") -> None:
        self._validate_priority(priority)
        event = QueuedAgentEvent(text=text, priority=priority)
        if self._agent_run is None:
            self._pending.append(event)
            return
        self._enqueue(event)

    def ingest_user_image(
        self,
        image_path: Path,
        *,
        caption: str = "",
        priority: EnqueuePriority = "asap",
    ) -> None:
        self._validate_priority(priority)
        message = self._format_image_message(image_path, caption=caption)
        self.ingest_user_text(message, priority=priority)

    def ingest_control_action(
        self,
        action: ControlAction,
        *,
        priority: EnqueuePriority = "asap",
    ) -> None:
        self._validate_priority(priority)
        if action == "new_session":
            self._pending.clear()
            self._reset_attached_run()
            return
        self.ingest_user_text(f"[用户控制事件]\naction: {action}", priority=priority)

    def flush(self) -> None:
        while self._agent_run is not None and self._pending:
            self._enqueue(self._pending.popleft())

    def _enqueue(self, event: QueuedAgentEvent) -> None:
        if self._agent_run is None:
            self._pending.appendleft(event)
            return
        self._agent_run.enqueue(event.text, priority=event.priority)

    def _reset_attached_run(self) -> None:
        reset_session = getattr(self._agent_run, "reset_session", None)
        if callable(reset_session):
            reset_session()

    def _validate_priority(self, priority: EnqueuePriority) -> None:
        if priority not in ("asap", "when_idle"):
            raise ValueError(f"Unsupported enqueue priority: {priority}")

    def _format_image_message(self, image_path: Path, *, caption: str = "") -> str:
        parts = [
            "[用户发送图片]",
            f"path: {image_path}",
        ]
        if caption.strip():
            parts.append(f"caption: {caption.strip()}")
        return "\n".join(parts)
