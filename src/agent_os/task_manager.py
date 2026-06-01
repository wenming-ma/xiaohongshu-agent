from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from .schemas import AgentToolResult
from .tools import AgentToolContext, AgentToolRegistry

TaskStatus = Literal["running", "succeeded", "failed", "cancelled"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentOSTaskRecord:
    task_id: str
    tool_name: str
    params: dict[str, Any]
    context: AgentToolContext
    status: TaskStatus = "running"
    result: AgentToolResult | None = None
    error_message: str | None = None
    attempt_of: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    _asyncio_task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "params": self.params,
            "error_message": self.error_message,
            "attempt_of": self.attempt_of,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result_summary": self.result.envelope.summary if self.result else "",
        }


class AgentOSTaskManager:
    """Runs specialist Agent tools independently from the main chat session."""

    def __init__(
        self,
        *,
        tool_registry: AgentToolRegistry,
        notifier: Any | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.notifier = notifier
        self._tasks: dict[str, AgentOSTaskRecord] = {}

    def start_task(
        self,
        tool_name: str,
        ctx: AgentToolContext,
        *,
        params: dict[str, Any] | None = None,
        task_id: str | None = None,
        attempt_of: str | None = None,
    ) -> AgentOSTaskRecord:
        tool = self.tool_registry.get(tool_name)
        if tool.category != "specialist":
            raise ValueError(f"Background task target must be a specialist tool: {tool_name}")

        resolved_task_id = task_id or uuid4().hex
        task_ctx = ctx.model_copy(update={"task_id": resolved_task_id})
        record = AgentOSTaskRecord(
            task_id=resolved_task_id,
            tool_name=tool_name,
            params=dict(params or {}),
            context=task_ctx,
            attempt_of=attempt_of,
        )
        self._tasks[record.task_id] = record
        record._asyncio_task = asyncio.create_task(self._run_task(record))
        return record

    def get_task(self, task_id: str) -> AgentOSTaskRecord:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent OS task: {task_id}") from exc

    def list_tasks(self) -> list[AgentOSTaskRecord]:
        return sorted(self._tasks.values(), key=lambda task: task.created_at)

    def restart_task(self, task_id: str) -> AgentOSTaskRecord:
        original = self.get_task(task_id)
        return self.start_task(
            original.tool_name,
            original.context,
            params=original.params,
            attempt_of=original.task_id,
        )

    async def wait_for_all(self) -> None:
        pending = [
            task._asyncio_task
            for task in self._tasks.values()
            if task._asyncio_task is not None and not task._asyncio_task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run_task(self, record: AgentOSTaskRecord) -> None:
        try:
            record.result = await self.tool_registry.execute(
                record.tool_name,
                record.context,
                **record.params,
            )
        except asyncio.CancelledError:
            record.status = "cancelled"
            record.finished_at = _utc_now()
            raise
        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            record.finished_at = _utc_now()
            await self._notify_failure(record)
            return

        record.status = "succeeded"
        record.finished_at = _utc_now()

    async def _notify_failure(self, record: AgentOSTaskRecord) -> None:
        if self.notifier is None:
            return
        message = (
            "后台任务失败\n"
            f"task_id: {record.task_id}\n"
            f"tool: {record.tool_name}\n"
            f"error: {record.error_message}"
        )
        send_message = getattr(self.notifier, "send_message", None)
        if callable(send_message):
            await send_message(message, chat_id=record.context.chat_id)
