from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..schemas import TranscriptionSegment


@dataclass(frozen=True)
class AlignmentResult:
    segments: list[TranscriptionSegment]
    duration_seconds: int = 0
    language: str = ""


class TimestampAligner(ABC):
    aligner_name = ""

    @abstractmethod
    def align(
        self,
        *,
        audio_path: Path,
        transcript: str,
        language: str,
    ) -> AlignmentResult:
        raise NotImplementedError

    def release(self) -> None:
        pass
