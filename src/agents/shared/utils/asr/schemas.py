from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker_id: int = 0


class TranscriptionResult(BaseModel):
    success: bool
    transcript: str = ""
    language: str = ""
    duration_seconds: int = 0
    segments: list[TranscriptionSegment] = Field(default_factory=list)
    error_message: str = ""
