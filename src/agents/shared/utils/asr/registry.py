from __future__ import annotations

from .alignment.reference_segments import ReferenceSegmentAligner
from .language.faster_whisper import FasterWhisperLanguageDetector
from .providers.base import AsrProvider
from .providers.cohere import CohereAsrProvider
from .providers.faster_whisper import FasterWhisperAsrProvider
from .providers.qwen import QwenAsrProvider


def normalize_provider_name(provider_name: str | None) -> str:
    normalized = (provider_name or "").strip().lower()
    if normalized in {"cohere", "cohere_transformers"}:
        return "cohere"
    if normalized in {"qwen", "qwen_asr", "qwen3_asr"}:
        return "qwen"
    if normalized in {"", "faster_whisper"}:
        return "faster_whisper"
    return normalized


def create_asr_provider(provider_name: str) -> AsrProvider:
    normalized = normalize_provider_name(provider_name)
    if normalized == "faster_whisper":
        return FasterWhisperAsrProvider()
    if normalized == "cohere":
        return CohereAsrProvider(
            language_detector=FasterWhisperLanguageDetector(),
            timestamp_aligner=ReferenceSegmentAligner(
                FasterWhisperAsrProvider(log_label="faster_whisper_reference")
            ),
        )
    if normalized == "qwen":
        return QwenAsrProvider()
    raise ValueError(f"未知 ASR_PROVIDER: {provider_name}")
