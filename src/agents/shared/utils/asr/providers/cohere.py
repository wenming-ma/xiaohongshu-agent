from __future__ import annotations

import gc
from pathlib import Path
from threading import Lock

from src.agents.video_post.schemas import SubtitleSegment, TranscriptionResult
from src.utils.logger import get_logger

from ..alignment.base import TimestampAligner
from ..language.base import LanguageDetector
from ..model_sources import (
    COHERE_ASR_MODEL_SPEC,
    is_hf_offline_mode,
    prepare_hf_cache_env,
    resolve_model_source,
)
from ..text_utils import build_transcription_result, empty_success_result, normalize_text
from .base import AsrProvider

logger = get_logger(__name__)


class CohereAsrProvider(AsrProvider):
    provider_name = "cohere"

    def __init__(
        self,
        *,
        language_detector: LanguageDetector,
        timestamp_aligner: TimestampAligner,
    ):
        self._language_detector = language_detector
        self._timestamp_aligner = timestamp_aligner
        self._processor = None
        self._model = None
        self._device = "cpu"
        self._model_lock = Lock()

    def _load_runtime(self) -> tuple[object, object]:
        if self._processor is not None and self._model is not None:
            return self._processor, self._model

        with self._model_lock:
            if self._processor is not None and self._model is not None:
                return self._processor, self._model

            prepare_hf_cache_env()

            try:
                import torch
                from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
            except Exception as exc:
                raise RuntimeError("缺少 Cohere ASR 所需依赖（transformers/torch）") from exc

            model_source, _ = resolve_model_source(COHERE_ASR_MODEL_SPEC)
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            local_files_only = is_hf_offline_mode()
            logger.info(
                "[ASR] 加载 provider=%s, source=%s, timestamps=aligned, language_detection=internal",
                self.provider_name,
                model_source,
            )

            self._processor = AutoProcessor.from_pretrained(
                model_source,
                trust_remote_code=True,
                local_files_only=local_files_only,
            )
            self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_source,
                trust_remote_code=True,
                local_files_only=local_files_only,
            )
            if hasattr(self._model, "to"):
                self._model = self._model.to(self._device)
            if hasattr(self._model, "eval"):
                self._model.eval()

        return self._processor, self._model

    def _transcribe_text(self, audio_path: Path, language: str) -> str:
        processor, model = self._load_runtime()
        if not hasattr(model, "transcribe"):
            raise RuntimeError("Cohere ASR 模型未暴露 transcribe 接口")

        texts = model.transcribe(
            processor=processor,
            audio_files=[str(audio_path)],
            language=language,
        )
        if not texts:
            return ""
        return normalize_text(str(texts[0]))

    def transcribe_audio(self, audio_path: Path) -> TranscriptionResult:
        if not audio_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {audio_path}")

        detected_language = (self._language_detector.detect_language(audio_path) or "").strip() or "en"
        transcript = self._transcribe_text(audio_path, detected_language)
        if not transcript:
            return empty_success_result(language=detected_language)

        alignment = self._timestamp_aligner.align(
            audio_path=audio_path,
            transcript=transcript,
            language=detected_language,
        )
        resolved_language = alignment.language or detected_language
        segments = alignment.segments
        if not segments:
            segments = [
                SubtitleSegment(
                    start=0.0,
                    end=max(float(alignment.duration_seconds), 0.01),
                    text=transcript,
                )
            ]

        return build_transcription_result(
            language=resolved_language,
            segments=segments,
            transcript=transcript,
            duration_seconds=alignment.duration_seconds,
        )

    def release(self) -> None:
        with self._model_lock:
            self._processor = None
            self._model = None
        self._language_detector.release()
        self._timestamp_aligner.release()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
