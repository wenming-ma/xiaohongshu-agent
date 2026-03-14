"""
Google Gemini Model 工厂
支持多 API key 轮换，并在指定模型失败后自动降级到备用模型

Key 来源（按优先级）：
1. GOOGLE_API_KEY / GEMINI_API_KEY
2. GEMINI_FALLBACK_API_KEYS（逗号分隔）

对上层 Agent 完全透明——返回的 Model 在 HTTP 层自动处理 key 轮换和模型降级。
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

_MODEL_FALLBACKS: dict[str, tuple[str, ...]] = {
    "gemini-2.5-pro": ("gemini-2.5-flash",),
}


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


def _resolve_model_chain(model_name: str) -> list[str]:
    models = [model_name]
    for fallback in _MODEL_FALLBACKS.get(model_name, ()):
        if fallback not in models:
            models.append(fallback)
    return models


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
    GoogleModel 包装器 —— 在 HTTP 层自动轮换 API key，并按模型链降级。

    继承 pydantic-ai Model ABC，对 Agent 完全透明。
    单轮顺序为：主模型轮完全部 key，再尝试备用模型轮完全部 key。
    若整轮都失败，则进入下一轮退避重试。
    """

    def __init__(self, model_name: str, key_pool: GoogleKeyPool) -> None:
        self._model_names = _resolve_model_chain(model_name)
        self._model_index = 0
        self._model_name_str = self._model_names[0]
        self._key_pool = key_pool
        self._inner = self._build()
        # 用内部 GoogleModel 的 settings 和 profile 初始化基类
        super().__init__(settings=self._inner.settings, profile=self._inner.profile)

    def _build(self) -> GoogleModel:
        provider = GoogleProvider(api_key=self._key_pool.current_key)
        return GoogleModel(self._model_name_str, provider=provider)

    # ── Model 协议（必须实现） ─────────────────────────────────────────────

    _MAX_RETRIES = 12  # 总轮数；每轮会遍历模型链，每个模型轮完全部 key

    @staticmethod
    def _backoff(attempt: int) -> float:
        """退避时间：5, 10, 15, ... 封顶 60s"""
        return min(5 * (attempt + 1), 60)

    def _set_model(self, model_name: str) -> None:
        self._model_name_str = model_name
        self._inner = self._build()
        self._settings = self._inner.settings
        # profile is a @cached_property — update underlying storage and invalidate cache
        self._profile = self._inner._profile
        self.__dict__.pop('profile', None)

    def _reset_to_primary_model(self) -> None:
        self._model_index = 0
        self._set_model(self._model_names[0])

    def _attempts_per_model(self) -> int:
        return max(1, self._key_pool.key_count)

    def _advance_retry_state(
        self,
        action: str,
        round_index: int,
        model_index: int,
        key_attempt: int,
        error: Exception,
    ) -> float:
        delay = self._backoff(round_index)
        self._key_pool.rotate()

        attempts_per_model = self._attempts_per_model()
        is_last_key_attempt = key_attempt + 1 >= attempts_per_model
        has_next_model = model_index + 1 < len(self._model_names)

        if not is_last_key_attempt:
            self._inner = self._build()
            logger.warning(
                "Google %s 失败 (第 %d/%d 轮, model=%s, key=%d/%d): %s — %ds 后轮换 key 重试",
                action,
                round_index + 1,
                self._MAX_RETRIES,
                self._model_name_str,
                key_attempt + 1,
                attempts_per_model,
                error,
                delay,
            )
            return delay

        if has_next_model:
            next_model = self._model_names[model_index + 1]
            logger.warning(
                "Google %s 失败 (第 %d/%d 轮, model=%s 已轮完全部 key): %s — %ds 后降级到 %s",
                action,
                round_index + 1,
                self._MAX_RETRIES,
                self._model_name_str,
                error,
                delay,
                next_model,
            )
            self._model_index = model_index + 1
            self._set_model(next_model)
            return delay

        logger.warning(
            "Google %s 失败 (第 %d/%d 轮, 所有模型和 key 已轮完): %s — %ds 后开始下一轮",
            action,
            round_index + 1,
            self._MAX_RETRIES,
            error,
            delay,
        )
        return delay

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        last_error: Exception | None = None
        for round_index in range(self._MAX_RETRIES):
            self._reset_to_primary_model()
            for model_index, model_name in enumerate(self._model_names):
                if self._model_name_str != model_name:
                    self._model_index = model_index
                    self._set_model(model_name)
                for key_attempt in range(self._attempts_per_model()):
                    try:
                        return await self._inner.request(messages, model_settings, model_request_parameters)
                    except Exception as e:
                        last_error = e
                        if not _is_retryable(e):
                            raise
                        delay = self._advance_retry_state("request", round_index, model_index, key_attempt, e)
                        await asyncio.sleep(delay)
                        continue
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
        for round_index in range(self._MAX_RETRIES):
            self._reset_to_primary_model()
            for model_index, model_name in enumerate(self._model_names):
                if self._model_name_str != model_name:
                    self._model_index = model_index
                    self._set_model(model_name)
                for key_attempt in range(self._attempts_per_model()):
                    try:
                        async with self._inner.request_stream(
                            messages, model_settings, model_request_parameters, run_context=run_context
                        ) as stream:
                            yield stream
                            return
                    except Exception as e:
                        last_error = e
                        if not _is_retryable(e):
                            raise
                        delay = self._advance_retry_state("stream", round_index, model_index, key_attempt, e)
                        await asyncio.sleep(delay)
                        continue
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
