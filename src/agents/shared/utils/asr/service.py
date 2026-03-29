from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Lock

from src.config.settings import ASRConfig
from src.utils.logger import get_logger

from .audio import extract_audio_track
from .providers.base import AsrProvider
from .registry import create_asr_provider, normalize_provider_name
from .text_utils import ensure_timestamped_transcription_result
from .types import TranscriptionResult

logger = get_logger(__name__)

_shared_asr_service: AsrService | None = None
_shared_asr_service_lock = Lock()


class AsrService:
    def __init__(self, provider_name: str | None = None):
        self.provider_name = normalize_provider_name(provider_name or ASRConfig.PROVIDER or "faster_whisper")
        self._provider: AsrProvider | None = None
        self._provider_lock = Lock()

    def get_provider(self) -> AsrProvider:
        if self._provider is not None:
            return self._provider

        with self._provider_lock:
            if self._provider is None:
                self._provider = create_asr_provider(self.provider_name)
        return self._provider

    async def transcribe_audio(self, audio_path: Path) -> TranscriptionResult:
        if not audio_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {audio_path}")

        provider = self.get_provider()
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, provider.transcribe_audio, audio_path)
        except Exception as exc:
            logger.error("[ASR] provider=%s 转录失败: %s", self.provider_name, exc)
            return TranscriptionResult(success=False, error_message=str(exc))

        return ensure_timestamped_transcription_result(result)

    async def transcribe_video(self, video_path: Path) -> TranscriptionResult:
        if not video_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {video_path}")

        audio_path: Path | None = None
        try:
            audio_path = await extract_audio_track(video_path)
            return await self.transcribe_audio(audio_path)
        except Exception as exc:
            logger.error("[ASR] 视频转录失败: %s", exc)
            return TranscriptionResult(success=False, error_message=str(exc))
        finally:
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)

    def release(self) -> None:
        with self._provider_lock:
            if self._provider is not None:
                self._provider.release()
                self._provider = None


def get_asr_service(provider_name: str | None = None) -> AsrService:
    global _shared_asr_service

    resolved_provider = normalize_provider_name(provider_name or ASRConfig.PROVIDER or "faster_whisper")
    with _shared_asr_service_lock:
        if _shared_asr_service is None or _shared_asr_service.provider_name != resolved_provider:
            if _shared_asr_service is not None:
                _shared_asr_service.release()
            _shared_asr_service = AsrService(resolved_provider)
    return _shared_asr_service


def release_asr_resources() -> None:
    global _shared_asr_service

    with _shared_asr_service_lock:
        if _shared_asr_service is not None:
            _shared_asr_service.release()
            _shared_asr_service = None


class AudioTranscriber:
    async def transcribe(self, video_path: Path) -> TranscriptionResult:
        return await get_asr_service().transcribe_video(video_path)
