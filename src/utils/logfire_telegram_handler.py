"""
Logfire Telegram Handler

通过 OpenTelemetry SpanProcessor 将 logfire 的日志事件发送到 Telegram。
捕获：
- 工具调用（playwright_browser_*, 等）
- LLM 调用（chat MiniMax-M2.1, 等）
- HTTP 请求（可选）
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import SpanKind

from .logger import get_logger
from .telegram_notifier import TelegramNotifier, get_telegram_notifier
from ..config.settings import TelegramConfig

logger = get_logger(__name__)


class TelegramSpanProcessor(SpanProcessor):
    """
    自定义 SpanProcessor，将 logfire 捕获的事件发送到 Telegram

    特点：
    - 过滤感兴趣的事件（工具调用、LLM 调用）
    - 限流避免刷屏（最小间隔时间）
    - 异步发送，不阻塞主流程
    """

    def __init__(
        self,
        notifier: Optional[TelegramNotifier] = None,
        *,
        min_interval_sec: float = 1.0,
        include_http_requests: bool = False,
        include_tool_args: bool = True,
        max_arg_length: int = 200,
        status_key: str = "logfire",
    ):
        """
        Args:
            notifier: Telegram 通知器（可选，默认使用全局单例）
            min_interval_sec: 最小发送间隔（秒），避免刷屏
            include_http_requests: 是否包含 HTTP 请求日志
            include_tool_args: 是否包含工具调用参数
            max_arg_length: 工具参数最大长度（超过会截断）
            status_key: Telegram 状态消息 key
        """
        self.notifier = notifier or get_telegram_notifier()
        self.min_interval_sec = min_interval_sec
        self.include_http_requests = include_http_requests
        self.include_tool_args = include_tool_args
        self.max_arg_length = max_arg_length
        self.status_key = status_key

        self._last_emit_at: float = 0.0
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def _enabled(self) -> bool:
        """检查是否启用 Telegram 反馈"""
        if not TelegramConfig.TOOL_FEEDBACK_ENABLED:
            return False
        if self.notifier is None or getattr(self.notifier, "bot", None) is None:
            return False
        if not getattr(self.notifier, "chat_id", None):
            return False
        return True

    def _should_emit(self) -> bool:
        """检查是否应该发送消息（限流）"""
        now = time.monotonic()
        if now - self._last_emit_at < self.min_interval_sec:
            return False
        self._last_emit_at = now
        return True

    def _get_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """获取或创建事件循环"""
        if self._event_loop is None or self._event_loop.is_closed():
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                # 没有运行中的事件循环
                return None
        return self._event_loop

    def _fire_and_forget(self, coro) -> None:
        """异步发送消息，不阻塞主流程"""
        try:
            loop = self._get_event_loop()
            if loop is not None:
                # 如果有运行中的事件循环，使用它
                task = loop.create_task(coro)
                # 添加回调来捕获异常
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            else:
                # 如果没有运行中的事件循环，尝试在新线程中运行
                import threading
                def run_in_thread():
                    try:
                        asyncio.run(coro)
                    except Exception as e:
                        logger.debug(f"Telegram 消息发送失败（忽略）: {e}")

                thread = threading.Thread(target=run_in_thread, daemon=True)
                thread.start()
        except Exception as e:
            # 发送失败不应该影响主流程
            logger.debug(f"Telegram 消息发送失败（忽略）: {e}")

    def _format_span_message(self, span: ReadableSpan) -> Optional[str]:
        """
        格式化 span 为 Telegram 消息

        Returns:
            消息文本，如果不需要发送则返回 None
        """
        name = span.name
        attributes = span.attributes or {}

        # 1. 工具调用 - span.name 是 'running tool'，工具名在 attributes 中
        if name == "running tool":
            tool_name = attributes.get("gen_ai.tool.name")
            if tool_name:
                message = f"🔧 {tool_name}"

                # 添加参数（如果启用）
                if self.include_tool_args:
                    # 尝试获取参数（可能的 key）
                    tool_args = (
                        attributes.get("tool_arguments") or
                        attributes.get("gen_ai.tool.call.arguments") or
                        attributes.get("tool_args")
                    )

                    if tool_args:
                        # 格式化参数
                        args_str = str(tool_args)
                        # 截断
                        if len(args_str) > self.max_arg_length:
                            args_str = args_str[:self.max_arg_length] + "..."
                        message += f"\n└─ {args_str}"

                return message

        # 工具调用 - instrumentation version >= 3 使用 'execute_tool xxx'
        if name.startswith("execute_tool "):
            tool_name = name.replace("execute_tool ", "")
            message = f"🔧 {tool_name}"

            # 添加参数（如果启用）
            if self.include_tool_args:
                tool_args = (
                    attributes.get("tool_arguments") or
                    attributes.get("gen_ai.tool.call.arguments") or
                    attributes.get("tool_args")
                )

                if tool_args:
                    args_str = str(tool_args)
                    if len(args_str) > self.max_arg_length:
                        args_str = args_str[:self.max_arg_length] + "..."
                    message += f"\n└─ {args_str}"

            return message

        # 2. LLM 调用
        if name.startswith("chat "):
            model_name = name.replace("chat ", "")
            return f"💬 {model_name}"

        # 3. HTTP 请求（可选）
        if self.include_http_requests and name == "HTTP POST":
            url = attributes.get("http.url", "")
            if "api.minimax.io" in url or "api.sagehub.cc" in url or "dashscope" in url:
                # 只显示关键的 API 请求
                return f"📡 API 请求"

        # 其他事件暂不处理
        return None

    def on_start(self, span: Span, parent_context=None) -> None:
        """Span 开始时调用"""
        if not self._enabled():
            return

        # 格式化消息
        message = self._format_span_message(span)
        if not message:
            return

        # 检查限流
        if not self._should_emit():
            return

        # 发送消息
        self._fire_and_forget(
            self.notifier.send_message(message)
        )

    def on_end(self, span: ReadableSpan) -> None:
        """Span 结束时调用"""
        # 可以在这里处理完成/失败的通知
        # 目前在 on_start 已经发送，这里暂不需要
        pass

    def shutdown(self) -> None:
        """关闭处理器"""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """强制刷新"""
        return True
