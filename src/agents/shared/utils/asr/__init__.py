from __future__ import annotations

from importlib import import_module
from typing import Any

from src.config.settings import ASRConfig

__all__ = [
    "ASRConfig",
    "AudioTranscriber",
    "AsrService",
    "COHERE_ASR_MODEL_SPEC",
    "FASTER_WHISPER_MODEL_SPEC",
    "HF_HOME_DIR",
    "HF_HUB_CACHE_DIR",
    "is_hf_offline_mode",
    "PROJECT_CACHE",
    "PROJECT_ROOT",
    "QWEN_ASR_MODEL_SPEC",
    "QWEN_FORCED_ALIGNER_MODEL_SPEC",
    "TranscriptionResult",
    "TranscriptionSegment",
    "extract_audio_track",
    "get_asr_service",
    "redistribute_transcript_to_segments",
    "release_asr_resources",
    "resolve_model_source",
    "resolve_model_source_from_root",
]


def __getattr__(name: str) -> Any:
    if name in {
        "COHERE_ASR_MODEL_SPEC",
        "FASTER_WHISPER_MODEL_SPEC",
        "HF_HOME_DIR",
        "HF_HUB_CACHE_DIR",
        "is_hf_offline_mode",
        "PROJECT_CACHE",
        "PROJECT_ROOT",
        "QWEN_ASR_MODEL_SPEC",
        "QWEN_FORCED_ALIGNER_MODEL_SPEC",
        "resolve_model_source",
        "resolve_model_source_from_root",
    }:
        module = import_module(".model_sources", __name__)
        return getattr(module, name)
    if name == "extract_audio_track":
        return import_module(".audio", __name__).extract_audio_track
    if name in {
        "AudioTranscriber",
        "AsrService",
        "get_asr_service",
        "release_asr_resources",
    }:
        module = import_module(".service", __name__)
        return getattr(module, name)
    if name in {"TranscriptionResult", "TranscriptionSegment"}:
        module = import_module(".schemas", __name__)
        return getattr(module, name)
    if name == "redistribute_transcript_to_segments":
        module = import_module(".alignment.reference_segments", __name__)
        return getattr(module, name)
    if name == "ASRConfig":
        return ASRConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
