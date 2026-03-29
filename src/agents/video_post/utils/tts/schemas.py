from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class NativeTimingEvent:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class TtsSynthesisRequest:
    text: str
    segment_index: int = 0
    language: str = "zh"
    voice: str = ""
    tone_tag: str = ""
    speaker_id: int = 0
    target_start: float = 0.0
    target_end: float = 0.0
    target_duration_seconds: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if self.target_duration_seconds > 0:
            return self.target_duration_seconds
        return max(self.target_end - self.target_start, 0.0)


@dataclass(slots=True)
class TtsSynthesisResult:
    audio_path: Path
    raw_duration_seconds: float = 0.0
    native_timing_events: tuple[NativeTimingEvent, ...] = ()
    timing_source: str = "none"
    provider_name: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TtsSynthesisContext:
    work_dir: Path
    reference_audio_path: Path | None = None
    voice: str = ""


@dataclass(slots=True)
class TtsSynthesisBatchResult:
    requests: list[TtsSynthesisRequest]
    success_map: dict[int, TtsSynthesisResult]
    provider_name: str
