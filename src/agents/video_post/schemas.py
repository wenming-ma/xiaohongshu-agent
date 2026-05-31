from enum import Enum
from typing import List

from pydantic import BaseModel, Field, computed_field

from src.agents.shared.utils.asr.schemas import TranscriptionResult


class Platform(str, Enum):
    YOUTUBE = "youtube"
    X = "x"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"


class EngagementMetrics(BaseModel):
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0


class VideoSource(BaseModel):
    url: str
    platform: Platform
    title: str = ""
    description: str = ""
    author: str = ""
    duration_seconds: int = 0
    video_width: int = 0
    video_height: int = 0
    engagement: EngagementMetrics = EngagementMetrics()
    thumbnail_url: str = ""

    @computed_field
    @property
    def engagement_score(self) -> int:
        return self.engagement.likes + self.engagement.comments * 2 + self.engagement.shares * 3


class VideoResearchResult(BaseModel):
    topic: str
    sources: List[VideoSource] = []
    keywords: List[str] = []
    summary: str = ""

    @computed_field
    @property
    def sources_count(self) -> int:
        return len(self.sources)


class SubtitleSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker_id: int = 0
    tone_tag: str = ""


class SubtitleResult(BaseModel):
    success: bool
    segments: List[SubtitleSegment] = []
    language: str = ""
    translated: bool = False
    srt_path: str = ""
    tts_srt_path: str = ""
    video_with_subs: str = ""
    error_message: str = ""


class DownloadResult(BaseModel):
    success: bool
    source: VideoSource
    local_path: str = ""
    file_size_bytes: int = 0
    format: str = ""
    duration_seconds: int = 0
    error_message: str = ""
    transcription: TranscriptionResult | None = None
    subtitle: SubtitleResult | None = None


class XHSVideoContent(BaseModel):
    title: str = Field(min_length=10, max_length=30)
    body: str = Field(min_length=50)
    hashtags: List[str] = Field(default=[], max_length=5)
    call_to_action: str = ""


class ContentReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: List[str] = []
    summary: str = ""


class CoverImageResult(BaseModel):
    success: bool
    cover_path: str = ""
    error_message: str = ""
