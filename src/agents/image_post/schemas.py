"""XHS Image Post Tool Schemas"""

from dataclasses import dataclass
from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Dict, Any, TypedDict


@dataclass
class ImageGenContext:
    """图片生成上下文（用于依赖注入）"""

    topic: str = ""
    image_type: str = ""
    validation_feedback: str = ""


class GroupSpec(TypedDict):
    title: str
    indices: list[int]


class CompactKeyInfo(TypedDict):
    index: int
    type: str | None
    name: str
    text: str


class ImageTypeSpec(TypedDict, total=False):
    type: str
    desc: str
    group_title: str
    indices: list[int]


class ResearchItem(BaseModel):
    title: str
    content: str
    item_type: Optional[str] = None
    source_ref: Optional[str] = None


class ContentSource(BaseModel):
    url: str
    title: str
    domain: str
    likes: Optional[int] = None
    comments: Optional[int] = None


class ResearchResult(BaseModel):
    summary: str
    items: List[ResearchItem] = []
    keywords: List[str] = []
    sources: List[ContentSource] = []

    @computed_field
    @property
    def items_count(self) -> int:
        return len(self.items)

    @computed_field
    @property
    def sources_count(self) -> int:
        return len(self.sources)


class XHSContent(BaseModel):
    title: str = Field(min_length=10, max_length=30)
    body: str = Field(min_length=100)
    hashtags: List[str] = Field(default=[], max_length=5)
    call_to_action: str = ""


class ReviewIssue(BaseModel):
    type: str
    severity: str
    description: str
    suggestion: str


class ReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: List[ReviewIssue] = []
    summary: str
    entity_usage: Optional[Dict[str, Any]] = None


class GeneratedImage(BaseModel):
    image_path: str
    prompt_used: str
    image_type: str


class ImageResult(BaseModel):
    images: List[GeneratedImage] = []
    total_count: int
    generated_at: str


class ImageGroupingGroup(BaseModel):
    title: str
    indices: List[int] = []
    rationale: Optional[str] = None


class ImageGroupingPlan(BaseModel):
    groups: List[ImageGroupingGroup] = []


class ImageGroupingReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: List[str] = []
    summary: str = ""


class ImageQualityReview(BaseModel):
    passed: bool
    text_clarity_score: float = Field(default=0.0, ge=0.0, le=100.0)
    style_score: float = Field(default=0.0, ge=0.0, le=100.0)
    aspect_ratio_correct: bool = True
    text_is_chinese: bool = True
    issues: List[str] = []
    summary: str


class ImageReadResult(BaseModel):
    extracted_text: str = ""
    description: str = ""
    language: str = "unknown"
    has_text: bool = False
    answer: str = ""
    issues: List[str] = []


class PostImageItem(BaseModel):
    """单张帖子图片的分析结果"""
    index: int
    url: str = ""
    extracted_text: str = ""
    description: str = ""
    has_text: bool = False
    issues: List[str] = []


class PostImagesReadResult(BaseModel):
    """帖子所有图片的汇总分析结果"""
    post_type: str = ""
    image_count: int = 0
    images: List[PostImageItem] = []
    issues: List[str] = []


class VideoReadResult(BaseModel):
    """视频语音转文字结果"""
    success: bool = False
    transcript: str = ""
    language: str = "unknown"
    duration_seconds: float = 0.0
    error_message: str = ""
