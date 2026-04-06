from __future__ import annotations

import os

from .....utils.logger import get_logger
from .registry import create_tts_provider, normalize_provider_name
from .schemas import TtsSynthesisBatchResult, TtsSynthesisContext, TtsSynthesisRequest

logger = get_logger(__name__)


def _configured_provider_name() -> str:
    return normalize_provider_name(os.getenv("VIDEO_DUB_TTS_PROVIDER", "fish"))


class TtsService:
    def __init__(self, provider_name: str | None = None):
        self.provider_name = normalize_provider_name(provider_name or _configured_provider_name())

    async def synthesize_many(
        self,
        requests: list[TtsSynthesisRequest],
        context: TtsSynthesisContext,
    ) -> TtsSynthesisBatchResult:
        if self.provider_name != "auto":
            provider = create_tts_provider(self.provider_name)
            return await provider.synthesize_many(requests, context)

        last_error: Exception | None = None
        for fallback_name in ("fish", "s2cpp", "qwen", "google"):
            provider = create_tts_provider(fallback_name)
            try:
                result = await provider.synthesize_many(requests, context)
            except Exception as exc:
                last_error = exc
                logger.warning("TTS provider=%s 失败，auto 继续回退: %s", fallback_name, exc)
                continue
            if result.success_map:
                return result
            logger.warning("TTS provider=%s 未生成可用配音段，auto 继续回退", fallback_name)

        if last_error is not None:
            raise RuntimeError(f"TTS auto 模式所有 provider 均失败: {last_error}") from last_error
        raise RuntimeError("TTS auto 模式未生成任何可用配音段")


def create_tts_service(provider_name: str | None = None) -> TtsService:
    return TtsService(provider_name=provider_name)
