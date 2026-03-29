from __future__ import annotations

from pathlib import Path

from .asr import (
    AudioTranscriber,
    FASTER_WHISPER_MODEL_SPEC,
    HF_HOME_DIR,
    HF_HUB_CACHE_DIR,
    PROJECT_CACHE,
    PROJECT_ROOT,
    FasterWhisperAsrProvider,
    extract_audio_track,
    get_asr_service,
    release_asr_resources,
    resolve_model_source_from_root,
)

TRANSCRIPTION_MODEL_REPO_ID = FASTER_WHISPER_MODEL_SPEC.repo_id
LOCAL_TRANSCRIPTION_MODEL_ROOT = HF_HUB_CACHE_DIR / FASTER_WHISPER_MODEL_SPEC.cache_root_name
LOCAL_TRANSCRIPTION_MODEL_PATH = LOCAL_TRANSCRIPTION_MODEL_ROOT / (
    FASTER_WHISPER_MODEL_SPEC.direct_model_dir_name or ""
)
LOCAL_TRANSCRIPTION_MODEL_SNAPSHOTS_DIR = LOCAL_TRANSCRIPTION_MODEL_ROOT / "snapshots"


def _resolve_transcription_model_source() -> tuple[str, str | None]:
    return resolve_model_source_from_root(
        LOCAL_TRANSCRIPTION_MODEL_ROOT,
        repo_id=TRANSCRIPTION_MODEL_REPO_ID,
        required_files=FASTER_WHISPER_MODEL_SPEC.required_files,
        direct_model_dir_name=LOCAL_TRANSCRIPTION_MODEL_PATH.name,
        cache_dir=HF_HUB_CACHE_DIR,
    )


def get_transcription_model():
    service = get_asr_service("faster_whisper")
    provider = service.get_provider()
    if not isinstance(provider, FasterWhisperAsrProvider):
        raise RuntimeError("默认转录模型 provider 不是 faster_whisper")
    return provider._load_model()


def release_transcription_model() -> None:
    release_asr_resources()


__all__ = [
    "AudioTranscriber",
    "HF_HOME_DIR",
    "HF_HUB_CACHE_DIR",
    "LOCAL_TRANSCRIPTION_MODEL_PATH",
    "LOCAL_TRANSCRIPTION_MODEL_ROOT",
    "LOCAL_TRANSCRIPTION_MODEL_SNAPSHOTS_DIR",
    "PROJECT_CACHE",
    "PROJECT_ROOT",
    "TRANSCRIPTION_MODEL_REPO_ID",
    "_resolve_transcription_model_source",
    "extract_audio_track",
    "get_asr_service",
    "get_transcription_model",
    "release_transcription_model",
]
