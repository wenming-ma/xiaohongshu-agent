from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Literal, Protocol


EnqueuePriority = Literal["asap", "when_idle"]


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
        if priority not in ("asap", "when_idle"):
            raise ValueError(f"Unsupported enqueue priority: {priority}")
        event = QueuedAgentEvent(text=text, priority=priority)
        if self._agent_run is None:
            self._pending.append(event)
            return
        self._enqueue(event)

    def flush(self) -> None:
        while self._agent_run is not None and self._pending:
            self._enqueue(self._pending.popleft())

    def _enqueue(self, event: QueuedAgentEvent) -> None:
        if self._agent_run is None:
            self._pending.appendleft(event)
            return
        self._agent_run.enqueue(event.text, priority=event.priority)
