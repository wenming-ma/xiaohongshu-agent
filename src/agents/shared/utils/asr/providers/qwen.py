from __future__ import annotations

import gc
from pathlib import Path
from threading import Lock

from src.agents.video_post.schemas import SubtitleSegment, TranscriptionResult
from src.utils.logger import get_logger

from ..model_sources import (
    QWEN_ASR_MODEL_SPEC,
    QWEN_FORCED_ALIGNER_MODEL_SPEC,
    prepare_cuda_library_path,
    prepare_hf_cache_env,
    resolve_model_source,
)
from ..text_utils import build_transcription_result, empty_success_result, normalize_text, visible_text_length
from .base import AsrProvider

logger = get_logger(__name__)

_QWEN_LANGUAGE_TO_CODE = {
    "arabic": "ar",
    "chinese": "zh",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "filipino": "fil",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hindi": "hi",
    "hungarian": "hu",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "macedonian": "mk",
    "malay": "ms",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "romanian": "ro",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "thai": "th",
    "turkish": "tr",
    "vietnamese": "vi",
    "cantonese": "yue",
    "wu language": "wuu",
    "minnan language": "nan",
}
_QWEN_DIALECT_MARKERS = {
    "anhui",
    "dongbei",
    "fujian",
    "gansu",
    "guizhou",
    "hebei",
    "henan",
    "hubei",
    "hunan",
    "jiangxi",
    "ningxia",
    "shandong",
    "shaanxi",
    "shanxi",
    "sichuan",
    "tianjin",
    "yunnan",
    "zhejiang",
}
_PUNCTUATION_PREFIXES = set(",.!?;:，。！？；：、)]}\"'")
_TERMINAL_PUNCTUATION = set(".!?。！？；;")
_MAX_SEGMENT_VISIBLE_CHARS = 24
_MAX_SEGMENT_DURATION_SECONDS = 4.5
_MAX_INTERSTAMP_GAP_SECONDS = 0.8


class QwenAsrProvider(AsrProvider):
    provider_name = "qwen"

    def __init__(self):
        self._model = None
        self._model_lock = Lock()

    def _resolve_dtype_and_device(self):
        try:
            import torch
        except Exception as exc:
            raise RuntimeError("缺少 Qwen ASR 所需依赖（torch/qwen-asr）") from exc

        if torch.cuda.is_available():
            cuda_supports_bf16 = bool(
                hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported()
            )
            return ("cuda:0", torch.bfloat16 if cuda_supports_bf16 else torch.float16)
        return ("cpu", torch.float32)

    def _load_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            prepare_hf_cache_env()
            prepare_cuda_library_path()

            try:
                from qwen_asr import Qwen3ASRModel
            except Exception as exc:
                raise RuntimeError("缺少 qwen-asr 依赖，无法加载 Qwen ASR provider") from exc

            model_source, _ = resolve_model_source(QWEN_ASR_MODEL_SPEC)
            aligner_source, _ = resolve_model_source(QWEN_FORCED_ALIGNER_MODEL_SPEC)
            device_map, dtype = self._resolve_dtype_and_device()
            logger.info(
                "[ASR] 加载 provider=%s, source=%s, forced_aligner=%s, timestamps=forced_aligner, language_detection=native",
                self.provider_name,
                model_source,
                aligner_source,
            )
            self._model = Qwen3ASRModel.from_pretrained(
                model_source,
                dtype=dtype,
                device_map=device_map,
                max_inference_batch_size=8,
                max_new_tokens=512,
                forced_aligner=aligner_source,
                forced_aligner_kwargs={
                    "dtype": dtype,
                    "device_map": device_map,
                },
            )

        return self._model

    @staticmethod
    def _normalize_language(language: str) -> str:
        normalized = (language or "").strip()
        if not normalized:
            return ""

        lowered = normalized.lower()
        if lowered in _QWEN_LANGUAGE_TO_CODE:
            return _QWEN_LANGUAGE_TO_CODE[lowered]
        if any(marker in lowered for marker in _QWEN_DIALECT_MARKERS):
            return "zh-dialect"
        if "cantonese" in lowered:
            return "yue"
        if "chinese" in lowered:
            return "zh"
        return lowered

    @staticmethod
    def _extract_stamp_value(stamp: object, *names: str) -> object | None:
        for name in names:
            if hasattr(stamp, name):
                value = getattr(stamp, name)
                if value is not None:
                    return value
            if isinstance(stamp, dict) and name in stamp and stamp[name] is not None:
                return stamp[name]
        return None

    def _extract_atomic_stamps(self, result: object) -> list[tuple[float, float, str]]:
        raw_stamps = getattr(result, "time_stamps", None) or getattr(result, "timestamps", None) or []
        if raw_stamps and isinstance(raw_stamps[0], (list, tuple)):
            flattened = []
            for group in raw_stamps:
                flattened.extend(group)
            raw_stamps = flattened

        atomic_stamps: list[tuple[float, float, str]] = []
        for stamp in raw_stamps:
            text = normalize_text(str(self._extract_stamp_value(stamp, "text", "token", "segment") or ""))
            start = self._extract_stamp_value(stamp, "start_time", "start")
            end = self._extract_stamp_value(stamp, "end_time", "end")
            if not text or start is None or end is None:
                continue
            start_value = float(start)
            end_value = max(float(end), start_value + 0.01)
            atomic_stamps.append((start_value, end_value, text))
        return atomic_stamps

    @staticmethod
    def _append_piece(current_text: str, piece: str) -> str:
        piece = normalize_text(piece)
        if not piece:
            return current_text
        if not current_text:
            return piece
        if piece[0] in _PUNCTUATION_PREFIXES:
            return f"{current_text}{piece}"
        if current_text[-1].isalnum() and piece[0].isalnum():
            return f"{current_text} {piece}"
        return f"{current_text}{piece}"

    def _collapse_atomic_stamps(
        self,
        atomic_stamps: list[tuple[float, float, str]],
    ) -> list[SubtitleSegment]:
        if not atomic_stamps:
            return []

        segments: list[SubtitleSegment] = []
        current_start = 0.0
        current_end = 0.0
        current_text = ""

        def flush() -> None:
            nonlocal current_start, current_end, current_text
            text = normalize_text(current_text)
            if text:
                segments.append(
                    SubtitleSegment(
                        start=current_start,
                        end=max(current_end, current_start + 0.01),
                        text=text,
                    )
                )
            current_start = 0.0
            current_end = 0.0
            current_text = ""

        for start, end, piece in atomic_stamps:
            if not current_text:
                current_start = start
                current_end = end
                current_text = piece
            else:
                if start - current_end >= _MAX_INTERSTAMP_GAP_SECONDS:
                    flush()
                    current_start = start
                    current_end = end
                    current_text = piece
                else:
                    current_text = self._append_piece(current_text, piece)
                    current_end = end

            should_flush = (
                piece[-1] in _TERMINAL_PUNCTUATION
                or visible_text_length(current_text) >= _MAX_SEGMENT_VISIBLE_CHARS
                or (current_end - current_start) >= _MAX_SEGMENT_DURATION_SECONDS
            )
            if should_flush:
                flush()

        flush()
        return segments

    def transcribe_audio(self, audio_path: Path) -> TranscriptionResult:
        if not audio_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {audio_path}")

        model = self._load_model()
        results = model.transcribe(
            audio=[str(audio_path)],
            language=None,
            return_time_stamps=True,
        )
        if not results:
            return empty_success_result()

        result = results[0]
        transcript = normalize_text(str(getattr(result, "text", "") or ""))
        language = self._normalize_language(str(getattr(result, "language", "") or ""))
        if not transcript:
            return empty_success_result(language=language)

        atomic_stamps = self._extract_atomic_stamps(result)
        segments = self._collapse_atomic_stamps(atomic_stamps)
        if not segments:
            last_end = atomic_stamps[-1][1] if atomic_stamps else 0.01
            segments = [
                SubtitleSegment(
                    start=0.0,
                    end=max(float(last_end), 0.01),
                    text=transcript,
                )
            ]

        duration_seconds = int(round(segments[-1].end)) if segments else 0
        return build_transcription_result(
            language=language,
            segments=segments,
            transcript=transcript,
            duration_seconds=duration_seconds,
        )

    def release(self) -> None:
        with self._model_lock:
            self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
