"""
Google Gemini Model 工厂
支持多 API key 轮换：请求失败时自动切换到下一个 key 重试

Key 来源（按优先级）：
1. GOOGLE_API_KEY / GEMINI_API_KEY
2. GEMINI_FALLBACK_API_KEYS（逗号分隔）

对上层 Agent 完全透明——返回的 Model 在 HTTP 层自动处理 key 轮换。
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from pydantic_ai.models import Model, ModelRequestParameters, ModelSettings, StreamedResponse
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai._run_context import RunContext

from ...config.settings import APIConfig

logger = logging.getLogger(__name__)

# 可重试的错误关键词（速率限制、配额、服务不可用）
_RETRYABLE_KEYWORDS = (
    "429", "quota", "rate", "limit", "resource_exhausted",
    "503", "overloaded", "unavailable", "capacity",
)


def _is_network_error(error: Exception) -> bool:
    """判断是否为网络层错误（httpx / httpcore 抛出的所有异常）。"""
    module = type(error).__module__ or ""
    return module.startswith(("httpx", "httpcore"))


def _is_retryable(error: Exception) -> bool:
    # httpx / httpcore 所有网络错误均可重试
    if _is_network_error(error):
        return True
    # 检查异常链（cause），网络错误经常被包装
    cause = error.__cause__
    while cause is not None:
        if _is_network_error(cause):
            return True
        cause = cause.__cause__
    # 按错误信息关键词匹配（速率限制、配额、服务不可用）
    msg = str(error).lower()
    return any(kw in msg for kw in _RETRYABLE_KEYWORDS)


# ── Key Pool ─────────────────────────────────────────────────────────────────

class GoogleKeyPool:
    """管理多个 Google API key，支持轮换。"""

    def __init__(self) -> None:
        keys: list[str] = []
        primary = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if primary:
            keys.append(primary)
        for k in APIConfig.GEMINI_FALLBACK_API_KEYS:
            if k and k not in keys:
                keys.append(k)
        if not keys:
            raise ValueError("GOOGLE_API_KEY 或 GEMINI_API_KEY 环境变量未设置")

        self.keys = keys
        self._index = 0
        logger.info("Google key pool: %d 个 key", len(self.keys))

    @property
    def current_key(self) -> str:
        return self.keys[self._index]

    @property
    def key_count(self) -> int:
        return len(self.keys)

    def rotate(self) -> bool:
        """切换到下一个 key。返回 True 表示成功切换。"""
        if len(self.keys) <= 1:
            return False
        old = self._index
        self._index = (self._index + 1) % len(self.keys)
        if self._index == old:
            return False
        logger.info("Google key 轮换: #%d -> #%d", old + 1, self._index + 1)
        return True


_key_pool: GoogleKeyPool | None = None


def _get_key_pool() -> GoogleKeyPool:
    global _key_pool
    if _key_pool is None:
        _key_pool = GoogleKeyPool()
    return _key_pool


# ── Resilient Model ──────────────────────────────────────────────────────────

class ResilientGoogleModel(Model):
    """
    GoogleModel 包装器 —— 在 HTTP 层自动轮换 API key。

    继承 pydantic-ai Model ABC，对 Agent 完全透明。
    当请求因速率限制/配额耗尽失败时，自动切换 key 并重建内部 GoogleModel 重试。
    """

    def __init__(self, model_name: str, key_pool: GoogleKeyPool) -> None:
        self._model_name_str = model_name
        self._key_pool = key_pool
        self._inner = self._build()
        # 用内部 GoogleModel 的 settings 和 profile 初始化基类
        super().__init__(settings=self._inner.settings, profile=self._inner.profile)

    def _build(self) -> GoogleModel:
        provider = GoogleProvider(api_key=self._key_pool.current_key)
        return GoogleModel(self._model_name_str, provider=provider)

    # ── Model 协议（必须实现） ─────────────────────────────────────────────

    _MAX_RETRIES = 12  # 总重试次数，每次失败轮换 key

    @staticmethod
    def _backoff(attempt: int) -> float:
        """退避时间：5, 10, 15, ... 封顶 60s"""
        return min(5 * (attempt + 1), 60)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        last_error: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return await self._inner.request(messages, model_settings, model_request_parameters)
            except Exception as e:
                last_error = e
                if _is_retryable(e):
                    self._key_pool.rotate()
                    self._inner = self._build()
                    delay = self._backoff(attempt)
                    logger.warning("Google request 失败 (%d/%d): %s — %ds 后轮换 key 重试",
                                   attempt + 1, self._MAX_RETRIES, e, delay)
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_error  # type: ignore[misc]

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        last_error: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                async with self._inner.request_stream(
                    messages, model_settings, model_request_parameters, run_context=run_context
                ) as stream:
                    yield stream
                    return
            except Exception as e:
                last_error = e
                if _is_retryable(e):
                    self._key_pool.rotate()
                    self._inner = self._build()
                    delay = self._backoff(attempt)
                    logger.warning("Google stream 失败 (%d/%d): %s — %ds 后轮换 key 重试",
                                   attempt + 1, self._MAX_RETRIES, e, delay)
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_error  # type: ignore[misc]

    def customize_request_parameters(self, model_request_parameters: ModelRequestParameters) -> ModelRequestParameters:
        return self._inner.customize_request_parameters(model_request_parameters)

    # ── 代理常用属性到内部 GoogleModel ────────────────────────────────────

    @property
    def model_name(self) -> str:  # type: ignore[override]
        return self._inner.model_name

    @property
    def system(self) -> str:  # type: ignore[override]
        return self._inner.system

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ── Public API ───────────────────────────────────────────────────────────────

def get_google_model(model_name: str | None = None) -> ResilientGoogleModel:
    """
    获取带自动 key 轮换的 Google Model。

    对调用方透明——返回的对象继承 pydantic-ai Model，
    遇到速率限制/配额错误时自动切换 key 重试。
    """
    pool = _get_key_pool()
    model_name = model_name or APIConfig.GOOGLE_MODEL
    return ResilientGoogleModel(model_name, pool)
