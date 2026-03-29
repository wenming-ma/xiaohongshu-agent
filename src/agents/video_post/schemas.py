from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, computed_field

from src.agents.shared.utils.asr.types import TranscriptionResult


class Platform(str, Enum):
    YOUTUBE = "youtube"
    X = "x"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"


class XHSVideoPostInput(BaseModel):
    topic: str
    audience: str
    platforms: List[Platform] = [Platform.YOUTUBE, Platform.X, Platform.INSTAGRAM, Platform.FACEBOOK, Platform.TIKTOK]
    max_videos: int = Field(default=10, ge=1, le=50)
    publish: bool = True


class XHSVideoPostOutput(BaseModel):
    success: bool
    title: str = ""
    body_preview: str = ""
    hashtags: list[str] = []
    video_path: str | None = None
    published: bool = False
    post_url: str | None = None
    output_dir: str = ""
    error_message: str | None = None


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


class VideoPublishResult(BaseModel):
    published: bool
    platform: str = "xiaohongshu"
    publish_time: str = ""
    post_url: str = ""
    error_message: str = ""
    retry_count: int = 0
    video_path: Optional[str] = None
    content_snapshot: Optional[Dict[str, Any]] = None
