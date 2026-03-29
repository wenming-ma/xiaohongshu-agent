from __future__ import annotations

import gc
from pathlib import Path
from threading import Lock

from ..model_sources import (
    FASTER_WHISPER_MODEL_SPEC,
    prepare_cuda_library_path,
    prepare_hf_cache_env,
    resolve_model_source,
)
from .base import LanguageDetector


class FasterWhisperLanguageDetector(LanguageDetector):
    detector_name = "faster_whisper"

    def __init__(self):
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
                raise RuntimeError("缺少 faster-whisper 依赖，无法加载语言检测器") from exc

            model_source, download_root = resolve_model_source(FASTER_WHISPER_MODEL_SPEC)
            try:
                self._model = WhisperModel(
                    model_source,
                    device="cuda",
                    compute_type="float16",
                    download_root=download_root,
                    local_files_only=True,
                )
            except Exception:
                self._model = WhisperModel(
                    model_source,
                    device="cpu",
                    compute_type="int8",
                    download_root=download_root,
                    local_files_only=True,
                )

        return self._model

    def detect_language(self, audio_path: Path) -> str:
        if not audio_path.exists():
            raise RuntimeError(f"文件不存在: {audio_path}")

        model = self._load_model()
        _segments_iter, info = model.transcribe(
            str(audio_path),
            language=None,
            task="transcribe",
            word_timestamps=False,
            vad_filter=True,
        )
        return (getattr(info, "language", "") or "").strip()

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
