from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from ...shared.utils.asr.model_sources import (
    QWEN_FORCED_ALIGNER_MODEL_SPEC,
    prepare_cuda_library_path,
    prepare_hf_cache_env,
    resolve_model_source,
)
from ....utils.logger import get_logger
from .tts.schemas import TtsSynthesisRequest, TtsSynthesisResult

logger = get_logger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_ALIGN_TOKEN_RE = re.compile(r"[A-Za-z0-9']+|[\u4e00-\u9fff]+|[^\s]")
_LANGUAGE_TO_QWEN = {
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "zh-hk": "Chinese",
    "zh-dialect": "Chinese",
    "yue": "Cantonese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ar": "Arabic",
    "ms": "Malay",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "fil": "Filipino",
    "fa": "Persian",
    "el": "Greek",
    "ro": "Romanian",
    "hu": "Hungarian",
    "mk": "Macedonian",
    "tr": "Turkish",
    "id": "Indonesian",
    "hi": "Hindi",
}


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text or "").strip()


def _visible_length(text: str) -> int:
    return len(_WHITESPACE_RE.sub("", _normalize_text(text)))


def _normalize_qwen_language(language: str) -> str:
    normalized = _normalize_text(language).lower()
    if not normalized:
        return "Chinese"
    return _LANGUAGE_TO_QWEN.get(normalized, "Chinese")


@dataclass(slots=True)
class AlignedToken:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class AlignmentResult:
    tokens: list[AlignedToken]
    aligner_used: str
    used_fallback: bool = False


@dataclass(slots=True)
class TtsTimingDecision:
    strategy_used: str
    stretch_ratio: float
    carryover_seconds: float
    target_duration_seconds: float
    final_duration_seconds: float
    aligner_used: str = ""
    used_fallback: bool = False


class TtsAligner(Protocol):
    name: str

    async def align_many(
        self,
        syntheses: list[TtsSynthesisResult],
        requests: list[TtsSynthesisRequest],
    ) -> list[AlignmentResult]:
        ...

    async def align(
        self,
        synthesis: TtsSynthesisResult,
        request: TtsSynthesisRequest,
    ) -> AlignmentResult:
        ...


class BoundaryAwareTtsAligner:
    """Fallback aligner that derives token timing from text boundaries."""

    name = "boundary_fallback"

    async def align_many(
        self,
        syntheses: list[TtsSynthesisResult],
        requests: list[TtsSynthesisRequest],
    ) -> list[AlignmentResult]:
        results: list[AlignmentResult] = []
        for synthesis, request in zip(syntheses, requests):
            if synthesis.native_timing_events:
                tokens = [
                    AlignedToken(
                        start=max(float(event.start), 0.0),
                        end=max(float(event.end), float(event.start)),
                        text=_normalize_text(event.text),
                    )
                    for event in synthesis.native_timing_events
                    if _normalize_text(event.text)
                ]
                results.append(AlignmentResult(tokens=tokens, aligner_used=synthesis.timing_source or "native"))
                continue

            normalized_text = _normalize_text(request.text)
            if not normalized_text:
                results.append(AlignmentResult(tokens=[], aligner_used=self.name))
                continue

            raw_tokens = _ALIGN_TOKEN_RE.findall(normalized_text)
            tokens_text = [token for token in raw_tokens if _normalize_text(token)]
            if not tokens_text:
                tokens_text = [normalized_text]

            total_duration = max(
                float(synthesis.raw_duration_seconds),
                float(request.target_duration_seconds),
                0.0,
            )
            if total_duration <= 0:
                total_duration = max(len(tokens_text) * 0.12, 0.12)

            weights = [max(_visible_length(token), 1) for token in tokens_text]
            total_weight = sum(weights) or len(tokens_text)

            cursor = 0.0
            tokens: list[AlignedToken] = []
            for index, (token, weight) in enumerate(zip(tokens_text, weights)):
                duration = total_duration * (weight / total_weight)
                end = total_duration if index == len(tokens_text) - 1 else cursor + duration
                tokens.append(
                    AlignedToken(
                        start=cursor,
                        end=max(end, cursor),
                        text=token,
                    )
                )
                cursor = end
            results.append(AlignmentResult(tokens=tokens, aligner_used=self.name))
        return results

    async def align(
        self,
        synthesis: TtsSynthesisResult,
        request: TtsSynthesisRequest,
    ) -> AlignmentResult:
        return (await self.align_many([synthesis], [request]))[0]


class QwenForcedTtsAligner:
    name = "qwen_forced_aligner"

    def __init__(self, fallback: TtsAligner | None = None):
        self._fallback = fallback or BoundaryAwareTtsAligner()
        self._model = None
        self._model_lock = Lock()

    def _resolve_dtype_and_device(self) -> tuple[str, object]:
        try:
            import torch
        except Exception as exc:
            raise RuntimeError("缺少 Qwen forced aligner 所需依赖（torch/qwen-asr）") from exc

        if torch.cuda.is_available():
            supports_bf16 = bool(
                hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported()
            )
            return "cuda:0", (torch.bfloat16 if supports_bf16 else torch.float16)
        return "cpu", torch.float32

    def _load_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            prepare_hf_cache_env()
            prepare_cuda_library_path()

            try:
                from qwen_asr import Qwen3ForcedAligner
            except Exception as exc:
                raise RuntimeError("缺少 qwen-asr forced aligner 依赖") from exc

            model_source, _ = resolve_model_source(QWEN_FORCED_ALIGNER_MODEL_SPEC)
            device_map, dtype = self._resolve_dtype_and_device()
            logger.info(
                "[TTS] 加载 aligner=%s source=%s device=%s",
                self.name,
                model_source,
                device_map,
            )
            self._model = Qwen3ForcedAligner.from_pretrained(
                model_source,
                device_map=device_map,
                dtype=dtype,
            )
        return self._model

    def _align_sync(
        self,
        syntheses: list[TtsSynthesisResult],
        requests: list[TtsSynthesisRequest],
    ) -> list[AlignmentResult]:
        model = self._load_model()
        audios = [str(synthesis.audio_path) for synthesis in syntheses]
        texts = [_normalize_text(request.text) for request in requests]
        languages = [_normalize_qwen_language(request.language) for request in requests]
        results = model.align(audio=audios, text=texts, language=languages)

        aligned_results: list[AlignmentResult] = []
        for result in results:
            tokens = [
                AlignedToken(
                    start=max(float(item.start_time), 0.0),
                    end=max(float(item.end_time), float(item.start_time)),
                    text=_normalize_text(item.text),
                )
                for item in result
                if _normalize_text(item.text)
            ]
            aligned_results.append(
                AlignmentResult(
                    tokens=tokens,
                    aligner_used=self.name,
                )
            )
        return aligned_results

    async def align_many(
        self,
        syntheses: list[TtsSynthesisResult],
        requests: list[TtsSynthesisRequest],
    ) -> list[AlignmentResult]:
        if not syntheses:
            return []

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._align_sync, syntheses, requests)
        except Exception as exc:
            logger.warning("Qwen forced aligner 不可用，回退边界对齐: %s", exc)
            fallback_results = await self._fallback.align_many(syntheses, requests)
            for result in fallback_results:
                result.used_fallback = True
            return fallback_results

    async def align(
        self,
        synthesis: TtsSynthesisResult,
        request: TtsSynthesisRequest,
    ) -> AlignmentResult:
        return (await self.align_many([synthesis], [request]))[0]


def create_tts_aligner() -> TtsAligner:
    return QwenForcedTtsAligner(fallback=BoundaryAwareTtsAligner())
