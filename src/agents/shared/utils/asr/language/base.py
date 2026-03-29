from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class LanguageDetector(ABC):
    detector_name = ""

    @abstractmethod
    def detect_language(self, audio_path: Path) -> str:
        raise NotImplementedError

    def release(self) -> None:
        pass
