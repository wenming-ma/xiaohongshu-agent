from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from src.config.settings import ArticleResearchConfig, ImageConfig, ResearchConfig

from .schemas import AgentToolResult
from .tools import AgentToolContext, AgentToolRegistry

TaskStatus = Literal["running", "succeeded", "failed", "cancelled"]
ScheduleStatus = Literal["scheduled", "running", "completed", "cancelled", "failed"]


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
            "human_summary": build_human_task_summary(self.tool_name, self.params),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result_summary": self.result.envelope.summary if self.result else "",
        }


@dataclass
class AgentOSScheduleRecord:
    schedule_id: str
    tool_name: str
    params: dict[str, Any]
    context: AgentToolContext
    delay_seconds: float = 0.0
    interval_seconds: float | None = None
    max_runs: int | None = 1
    status: ScheduleStatus = "scheduled"
    run_count: int = 0
    task_ids: list[str] = field(default_factory=list)
    error_message: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    next_run_at: datetime | None = None
    finished_at: datetime | None = None
    _asyncio_task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_summary(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "params": self.params,
            "delay_seconds": self.delay_seconds,
            "interval_seconds": self.interval_seconds,
            "max_runs": self.max_runs,
            "run_count": self.run_count,
            "task_ids": list(self.task_ids),
            "error_message": self.error_message,
            "human_summary": build_human_task_summary(self.tool_name, self.params),
            "created_at": self.created_at.isoformat(),
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
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
        self._schedules: dict[str, AgentOSScheduleRecord] = {}
        self._resource_locks: dict[str, asyncio.Lock] = {}

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
        task_ctx = ctx.model_copy(
            update={
                "run_id": resolved_task_id,
                "task_id": resolved_task_id,
                "metadata": {
                    **dict(ctx.metadata),
                    "parent_run_id": ctx.run_id,
                },
            }
        )
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

    def schedule_task(
        self,
        tool_name: str,
        ctx: AgentToolContext,
        *,
        params: dict[str, Any] | None = None,
        schedule_id: str | None = None,
        delay_seconds: float = 0.0,
        interval_seconds: float | None = None,
        max_runs: int | None = 1,
    ) -> AgentOSScheduleRecord:
        tool = self.tool_registry.get(tool_name)
        if tool.category != "specialist":
            raise ValueError(f"Scheduled task target must be a specialist tool: {tool_name}")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be >= 0")
        if interval_seconds is not None and interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        if max_runs is not None and max_runs < 1:
            raise ValueError("max_runs must be >= 1")

        record = AgentOSScheduleRecord(
            schedule_id=schedule_id or uuid4().hex,
            tool_name=tool_name,
            params=dict(params or {}),
            context=ctx,
            delay_seconds=delay_seconds,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            next_run_at=_utc_now() + timedelta(seconds=delay_seconds),
        )
        self._schedules[record.schedule_id] = record
        record._asyncio_task = asyncio.create_task(self._run_schedule(record))
        return record

    def get_task(self, task_id: str) -> AgentOSTaskRecord:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent OS task: {task_id}") from exc

    def list_tasks(self) -> list[AgentOSTaskRecord]:
        return sorted(self._tasks.values(), key=lambda task: task.created_at)

    def get_schedule(self, schedule_id: str) -> AgentOSScheduleRecord:
        try:
            return self._schedules[schedule_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent OS schedule: {schedule_id}") from exc

    def list_schedules(self) -> list[AgentOSScheduleRecord]:
        return sorted(self._schedules.values(), key=lambda schedule: schedule.created_at)

    def restart_task(self, task_id: str) -> AgentOSTaskRecord:
        original = self.get_task(task_id)
        return self.start_task(
            original.tool_name,
            original.context,
            params=original.params,
            attempt_of=original.task_id,
        )

    def cancel_task(self, task_id: str) -> AgentOSTaskRecord:
        record = self.get_task(task_id)
        if record.status != "running":
            return record
        if record._asyncio_task is not None and not record._asyncio_task.done():
            record._asyncio_task.cancel()
        else:
            record.status = "cancelled"
            record.finished_at = _utc_now()
        return record

    def cancel_schedule(self, schedule_id: str) -> AgentOSScheduleRecord:
        record = self.get_schedule(schedule_id)
        if record.status in ("completed", "cancelled", "failed"):
            return record
        record.status = "cancelled"
        record.finished_at = _utc_now()
        if record._asyncio_task is not None and not record._asyncio_task.done():
            record._asyncio_task.cancel()
        return record

    async def wait_for_all(self) -> None:
        pending = [
            task._asyncio_task
            for task in self._tasks.values()
            if task._asyncio_task is not None and not task._asyncio_task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def wait_for_schedules(self) -> None:
        pending = [
            schedule._asyncio_task
            for schedule in self._schedules.values()
            if schedule._asyncio_task is not None and not schedule._asyncio_task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run_schedule(self, record: AgentOSScheduleRecord) -> None:
        try:
            if record.delay_seconds > 0:
                await asyncio.sleep(record.delay_seconds)
            record.status = "running"
            while record.status == "running":
                task = self.start_task(
                    record.tool_name,
                    record.context,
                    params=record.params,
                )
                record.task_ids.append(task.task_id)
                record.run_count += 1
                if task._asyncio_task is not None:
                    await task._asyncio_task

                if record.max_runs is not None and record.run_count >= record.max_runs:
                    record.status = "completed"
                    record.finished_at = _utc_now()
                    return
                if record.interval_seconds is None:
                    record.status = "completed"
                    record.finished_at = _utc_now()
                    return
                record.next_run_at = _utc_now() + timedelta(seconds=record.interval_seconds)
                await asyncio.sleep(record.interval_seconds)
        except asyncio.CancelledError:
            record.status = "cancelled"
            record.finished_at = _utc_now()
            raise
        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            record.finished_at = _utc_now()

    async def _run_task(self, record: AgentOSTaskRecord) -> None:
        tool = self.tool_registry.get(record.tool_name)
        if tool.resource_group:
            lock = self._resource_locks.setdefault(tool.resource_group, asyncio.Lock())
            async with lock:
                await self._execute_record(record)
            return
        await self._execute_record(record)

    async def _execute_record(self, record: AgentOSTaskRecord) -> None:
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
        if record.result.envelope.status != "success":
            record.status = "failed"
            record.error_message = (
                record.result.envelope.error_message
                or record.result.envelope.summary
                or "background task returned an error envelope"
            )
        record.finished_at = _utc_now()
        if record.status == "failed":
            await self._notify_failure(record)

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


def build_human_task_summary(tool_name: str, params: dict[str, Any]) -> str:
    spec = params.get("spec") if isinstance(params, dict) else None
    if not isinstance(spec, dict):
        title = str(params.get("title") or params.get("objective") or tool_name)
        return f"{tool_name}｜{title}"

    route = str(spec.get("route") or _route_from_tool_name(tool_name) or tool_name)
    topic = str(spec.get("topic") or spec.get("objective") or "未命名任务")
    style_constraints = [
        str(item)
        for item in (spec.get("style_constraints") or [])
        if str(item).strip()
    ]
    run_options = spec.get("run_options") if isinstance(spec.get("run_options"), dict) else {}
    image_options = run_options.get("image") if isinstance(run_options.get("image"), dict) else {}
    research_options = run_options.get("research") if isinstance(run_options.get("research"), dict) else {}

    image_count = image_options.get("count")
    image_text = f"{image_count}张" if image_count else f"自动上限{ImageConfig.MAX_AUTO_IMAGES}"
    research_text = _research_summary(route, research_options)
    style_text = "、".join(style_constraints) if style_constraints else "默认"
    return f"{route}｜{topic}｜图片：{image_text}｜研究：{research_text}｜风格：{style_text}"


def _route_from_tool_name(tool_name: str) -> str | None:
    return {
        "execute_image_post": "image_post",
        "execute_article_post": "article_post",
        "execute_video_post": "video_post",
    }.get(tool_name)


def _research_summary(route: str, research_options: dict[str, Any]) -> str:
    research_max_items = research_options.get("max_items")
    if research_max_items:
        if route == "image_post":
            return f"{research_max_items}帖/{research_max_items}轮"
        return f"{research_max_items}项/{research_max_items}轮"
    if route == "image_post":
        return f"{ResearchConfig.MIN_POSTS_RESEARCHED}帖/{ResearchConfig.VALIDATION_MAX_RETRIES}轮"
    if route == "article_post":
        return (
            f"{ArticleResearchConfig.MIN_SOURCE_PAGES}-"
            f"{ArticleResearchConfig.MAX_SOURCE_PAGES}源/"
            f"{ArticleResearchConfig.MAX_ITERATIONS}轮"
        )
    if route == "video_post":
        return "10轮/5视频"
    return "默认"
