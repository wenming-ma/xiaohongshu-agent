"""Schemas for Xiaohongshu video extraction."""

from pydantic import BaseModel


class VideoUrlExtractResult(BaseModel):
    success: bool = False
    video_url: str = ""
    current_page_url: str = ""
    note_id: str = ""
    source: str = ""
    error_message: str = ""


class VideoReadResult(BaseModel):
    success: bool = False
    transcript: str = ""
    language: str = "unknown"
    duration_seconds: float = 0.0
    error_message: str = ""
