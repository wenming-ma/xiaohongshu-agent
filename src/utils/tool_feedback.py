"""
Tool execution feedback (Telegram).

Wrap pydantic-ai toolsets so every tool call can report start/success/failure to Telegram.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from pydantic_ai import RunContext, Tool
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset, FunctionToolset, ToolsetTool, WrapperToolset

from ..config.settings import TelegramConfig
from .logger import get_logger
from .telegram_notifier import TelegramNotifier, get_telegram_notifier

logger = get_logger(__name__)


def _to_compact_json(value: Any, *, max_len: int) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        s = value
    else:
        try:
            s = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            s = str(value)
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _fire_and_forget(coro: Any) -> None:
    try:
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: t.exception())  # surface exceptions to event loop/logs
    except Exception:
        # tool execution must never fail because feedback failed
        pass


@dataclass
class TelegramToolFeedbackToolset(WrapperToolset[Any]):
    """Wrap a toolset and report tool calls to Telegram."""

    notifier: TelegramNotifier | None = None
    status_key: str = "tool_feedback"
    min_interval_sec: float = 0.8
    include_args: bool = True
    include_result: bool = False
    max_field_len: int = 900

    _last_emit_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.notifier is None:
            self.notifier = get_telegram_notifier()

    def _enabled(self) -> bool:
        if not TelegramConfig.TOOL_FEEDBACK_ENABLED:
            return False
        if self.notifier is None or getattr(self.notifier, "bot", None) is None:
            return False
        if not getattr(self.notifier, "chat_id", None):
            return False
        return True

    def _should_emit(self) -> bool:
        now = time.monotonic()
        if now - self._last_emit_at < self.min_interval_sec:
            return False
        self._last_emit_at = now
        return True

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: RunContext[Any], tool: ToolsetTool[Any]) -> Any:
        if self._enabled() and self._should_emit():
            parts = [f"🔧 tool: {name}"]
            if self.include_args:
                parts.append(f"args: {_to_compact_json(tool_args, max_len=self.max_field_len)}")
            parts.append(f"step: {getattr(ctx, 'run_step', '?')}  retry: {getattr(ctx, 'retry', 0)}")
            _fire_and_forget(self.notifier.upsert_status("\n".join(parts), key=self.status_key))  # type: ignore[union-attr]

        started_at = time.monotonic()
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as e:
            if self._enabled() and self._should_emit():
                elapsed = time.monotonic() - started_at
                msg = f"❌ tool error: {name}\nerror: {type(e).__name__}: {str(e)[:300]}\nelapsed: {elapsed:.2f}s"
                _fire_and_forget(self.notifier.upsert_status(msg, key=self.status_key))  # type: ignore[union-attr]
            raise

        if self._enabled() and self._should_emit():
            elapsed = time.monotonic() - started_at
            parts = [f"✅ tool ok: {name}", f"elapsed: {elapsed:.2f}s"]
            if self.include_result:
                parts.append(f"result: {_to_compact_json(result, max_len=self.max_field_len)}")
            _fire_and_forget(self.notifier.upsert_status("\n".join(parts), key=self.status_key))  # type: ignore[union-attr]

        return result


def build_toolset_with_telegram_feedback(
    *,
    toolsets: Sequence[AbstractToolset[Any]] | None = None,
    tools: Sequence[Tool[Any] | Any] | None = None,
) -> AbstractToolset[Any]:
    """
    Build a single toolset that combines toolsets + function tools, then (optionally) wraps with Telegram feedback.

    This is used to ensure "all tool calls" (including function tools passed via Agent.tools) go through the wrapper.
    """
    toolsets = list(toolsets or [])
    tools = list(tools or [])

    if tools:
        toolsets.append(FunctionToolset(tools=tools))

    if not toolsets:
        raise ValueError("build_toolset_with_telegram_feedback requires at least one toolset or tool")

    combined: AbstractToolset[Any]
    if len(toolsets) == 1:
        combined = toolsets[0]
    else:
        combined = CombinedToolset(toolsets=toolsets)

    if TelegramConfig.TOOL_FEEDBACK_ENABLED:
        combined = TelegramToolFeedbackToolset(wrapped=combined)

    return combined

