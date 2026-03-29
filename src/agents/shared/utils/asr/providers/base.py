from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..types import TranscriptionResult


class AsrProvider(ABC):
    provider_name = ""

    @abstractmethod
    def transcribe_audio(self, audio_path: Path) -> TranscriptionResult:
        raise NotImplementedError

    def release(self) -> None:
        pass
