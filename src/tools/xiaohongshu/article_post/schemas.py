"""Schemas for the Xiaohongshu long-form article tool."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class ArticleStrategy(str, Enum):
    AUTO = "auto"
    SYNTHESIZE = "synthesize"
    REPURPOSE_ARTICLE = "repurpose_article"
    REPURPOSE_VIDEO = "repurpose_video"


class ArticleSourceType(str, Enum):
    ARTICLE = "article"
    VIDEO = "video"
    EMBEDDED_VIDEO = "embedded_video"


class ArticleBlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    BULLET_LIST = "bullet_list"
    NUMBERED_LIST = "numbered_list"
    QUOTE = "quote"
    IMAGE_SLOT = "image_slot"


class XHSArticlePostInput(BaseModel):
    topic: str
    audience: str
    publish: bool = True
    generate_images: bool = True
    strategy: ArticleStrategy = ArticleStrategy.AUTO


class XHSArticlePostOutput(BaseModel):
    success: bool
    title: str = ""
    body_preview: str = ""
    hashtags: list[str] = []
    image_count: int = 0
    image_paths: list[str] = []
    published: bool = False
    post_url: str | None = None
    output_dir: str = ""
    error_message: str | None = None


class ArticleSource(BaseModel):
    source_ref: str
    source_type: ArticleSourceType
    url: str
    domain: str
    title: str = ""
    author: str = ""
    published_at: str = ""
    excerpt: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    engagement_hint: str = ""
    paywall_status: str = "public"
    duration_seconds: float = 0.0
    transcript_available: bool = False


class SourceChunk(BaseModel):
    chunk_id: str
    source_ref: str
    chunk_type: str = "paragraph"
    heading: str = ""
    text: str
    order: int = 0


class SourceDigest(BaseModel):
    source_ref: str
    source_type: ArticleSourceType
    url: str
    domain: str
    title: str = ""
    author: str = ""
    published_at: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    engagement_hint: str = ""
    paywall_status: str = "public"
    transcript_available: bool = False
    headings: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    evidence_queries: list[str] = Field(default_factory=list)
    risk_notes: str = ""


class SourceExcerpt(BaseModel):
    source_ref: str
    chunk_id: str
    heading: str = ""
    reason: str = ""
    text: str


class SavedSourceIndex(BaseModel):
    source_ref: str
    source_type: ArticleSourceType
    title: str = ""
    domain: str = ""
    source_path: str
    chunk_count: int = 0


class VideoTranscript(BaseModel):
    success: bool = False
    transcript: str = ""
    language: str = "unknown"
    duration_seconds: float = 0.0
    source_ref: str = ""
    error_message: str = ""


class ArticleClaim(BaseModel):
    claim: str
    detail: str = ""
    source_refs: list[str] = []
    confidence: str = "medium"
    section_hint: str = ""


class ArticleResearchResult(BaseModel):
    summary: str = ""
    sources: list[ArticleSource] = []
    claims: list[ArticleClaim] = []
    transcripts: list[VideoTranscript] = []
    keywords: list[str] = []
    primary_source_ref: str = ""
    suggested_strategy: ArticleStrategy = ArticleStrategy.SYNTHESIZE
    notes: str = ""

    @computed_field
    @property
    def sources_count(self) -> int:
        return len(self.sources)

    @computed_field
    @property
    def unique_domains_count(self) -> int:
        return len({source.domain for source in self.sources if source.domain})


class ArticleBlock(BaseModel):
    block_type: ArticleBlockType
    text: str = ""
    items: list[str] = []
    image_key: str = ""
    source_refs: list[str] = []


class ArticleSection(BaseModel):
    heading: str
    summary: str = ""
    blocks: list[ArticleBlock] = []
    source_refs: list[str] = []


class XHSArticleContent(BaseModel):
    strategy: ArticleStrategy = ArticleStrategy.SYNTHESIZE
    title: str = Field(min_length=10, max_length=64)
    lead: str = Field(min_length=30)
    attribution_line: str = ""
    sections: list[ArticleSection] = Field(default_factory=list, min_length=2)
    closing: str = ""
    hashtags: list[str] = Field(default_factory=list, max_length=8)
    rendered_body: str = ""
    primary_source_ref: str = ""
    source_summary: str = ""

    @computed_field
    @property
    def word_count(self) -> int:
        text = "\n".join(
            [
                self.lead,
                *(section.summary for section in self.sections),
                self.closing,
            ]
        )
        return len(text)

    @computed_field
    @property
    def image_keys(self) -> list[str]:
        keys: list[str] = []
        for section in self.sections:
            for block in section.blocks:
                if block.block_type == ArticleBlockType.IMAGE_SLOT and block.image_key:
                    keys.append(block.image_key)
        return keys


class ReviewDimension(str, Enum):
    STRUCTURE = "structure"
    ACCURACY = "accuracy"
    READABILITY = "readability"
    NATURALNESS = "naturalness"


class ArticleReviewIssue(BaseModel):
    dimension: ReviewDimension
    severity: str = Field(description="critical / warning / info")
    description: str
    suggestion: str = ""


class DimensionReviewResult(BaseModel):
    dimension: ReviewDimension
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: list[ArticleReviewIssue] = []
    summary: str = ""


class ArticleReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: list[ArticleReviewIssue] = []
    dimension_results: list[DimensionReviewResult] = []
    summary: str = ""


class ArticleImageSpec(BaseModel):
    image_key: str
    label: str
    prompt_hint: str
    source_refs: list[str] = []


class GeneratedArticleImage(BaseModel):
    image_key: str
    image_path: str
    prompt_used: str


class ArticleImageResult(BaseModel):
    images: list[GeneratedArticleImage] = []
    total_count: int = 0
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ArticlePublishResult(BaseModel):
    published: bool
    platform: str = "xiaohongshu"
    publish_time: str = ""
    post_url: str = ""
    error_message: str = ""
    retry_count: int = 0
    content_snapshot: dict[str, Any] | None = None
    image_paths: list[str] | None = None
