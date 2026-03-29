from __future__ import annotations

import gc
from pathlib import Path
from threading import Lock

from src.utils.logger import get_logger

from ..model_sources import (
    FASTER_WHISPER_MODEL_SPEC,
    is_hf_offline_mode,
    prepare_cuda_library_path,
    prepare_hf_cache_env,
    resolve_model_source,
)
from ..text_utils import build_transcription_result, empty_success_result, normalize_text
from ..schemas import TranscriptionResult, TranscriptionSegment
from .base import AsrProvider

logger = get_logger(__name__)


class FasterWhisperAsrProvider(AsrProvider):
    provider_name = "faster_whisper"

    def __init__(self, *, log_label: str | None = None):
        self._log_label = log_label or self.provider_name
        self._model = None
        self._model_lock = Lock()

    def _load_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            prepare_hf_cache_env()
            prepare_cuda_library_path()

            try:
                from faster_whisper import WhisperModel
            except Exception as exc:
                raise RuntimeError("缺少 faster-whisper 依赖，无法加载 ASR provider") from exc

            model_source, download_root = resolve_model_source(FASTER_WHISPER_MODEL_SPEC)
            logger.info(
                "[ASR] 加载 provider=%s, source=%s, timestamps=native, language_detection=native",
                self._log_label,
                model_source,
            )
            local_files_only = is_hf_offline_mode()

            try:
                self._model = WhisperModel(
                    model_source,
                    device="cuda",
                    compute_type="float16",
                    download_root=download_root,
                    local_files_only=local_files_only,
                )
            except Exception as exc:
                logger.warning("[ASR] provider=%s CUDA 加载失败，回退 CPU: %s", self._log_label, exc)
                self._model = WhisperModel(
                    model_source,
                    device="cpu",
                    compute_type="int8",
                    download_root=download_root,
                    local_files_only=local_files_only,
                )

        return self._model

    def transcribe_audio(self, audio_path: Path) -> TranscriptionResult:
        if not audio_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {audio_path}")

        model = self._load_model()
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=None,
            task="transcribe",
            word_timestamps=True,
            vad_filter=True,
        )
        segments = [
            TranscriptionSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=normalize_text(segment.text),
            )
            for segment in segments_iter
            if normalize_text(segment.text)
        ]
        detected_language = (getattr(info, "language", "") or "").strip()
        if not segments:
            return empty_success_result(language=detected_language)
        return build_transcription_result(
            language=detected_language,
            segments=segments,
        )

    def release(self) -> None:
        with self._model_lock:
            if self._model is not None:
                del self._model
                self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
