from src.config.settings import ASRConfig

from .alignment.reference_segments import redistribute_transcript_to_segments
from .audio import extract_audio_track
from .model_sources import (
    COHERE_ASR_MODEL_SPEC,
    FASTER_WHISPER_MODEL_SPEC,
    HF_HOME_DIR,
    HF_HUB_CACHE_DIR,
    PROJECT_CACHE,
    PROJECT_ROOT,
    QWEN_ASR_MODEL_SPEC,
    QWEN_FORCED_ALIGNER_MODEL_SPEC,
    resolve_model_source,
    resolve_model_source_from_root,
)
from .providers.cohere import CohereAsrProvider
from .providers.faster_whisper import FasterWhisperAsrProvider
from .providers.qwen import QwenAsrProvider
from .service import AudioTranscriber, AsrService, get_asr_service, release_asr_resources

__all__ = [
    "ASRConfig",
    "AudioTranscriber",
    "AsrService",
    "COHERE_ASR_MODEL_SPEC",
    "FASTER_WHISPER_MODEL_SPEC",
    "HF_HOME_DIR",
    "HF_HUB_CACHE_DIR",
    "PROJECT_CACHE",
    "PROJECT_ROOT",
    "QWEN_ASR_MODEL_SPEC",
    "QWEN_FORCED_ALIGNER_MODEL_SPEC",
    "CohereAsrProvider",
    "FasterWhisperAsrProvider",
    "QwenAsrProvider",
    "extract_audio_track",
    "get_asr_service",
    "redistribute_transcript_to_segments",
    "release_asr_resources",
    "resolve_model_source",
    "resolve_model_source_from_root",
]
