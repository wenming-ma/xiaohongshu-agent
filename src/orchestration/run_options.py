from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.config.settings import (
    APIConfig,
    ArticleContentConfig,
    ArticleImageConfig,
    ArticleResearchConfig,
    ImageConfig,
    ResearchConfig,
    RetryConfig,
)


class ResearchRunOptions(BaseModel):
    """Runtime knobs for one research-agent invocation."""

    min_posts_researched: int = Field(default_factory=lambda: ResearchConfig.MIN_POSTS_RESEARCHED, ge=1)
    validation_max_retries: int = Field(default_factory=lambda: ResearchConfig.VALIDATION_MAX_RETRIES, ge=1)
    min_key_infos: int = Field(default_factory=lambda: ResearchConfig.MIN_KEY_INFOS, ge=1)
    min_cases: int = Field(default_factory=lambda: ResearchConfig.MIN_CASES, ge=0)
    max_new_posts_per_iteration: int = Field(
        default_factory=lambda: ResearchConfig.MAX_NEW_POSTS_PER_ITERATION,
        ge=1,
    )
    per_iteration_request_limit: int = Field(
        default_factory=lambda: ResearchConfig.PER_ITERATION_REQUEST_LIMIT,
        ge=1,
    )
    per_iteration_tool_calls_limit: int = Field(
        default_factory=lambda: ResearchConfig.PER_ITERATION_TOOL_CALLS_LIMIT,
        ge=1,
    )

class ImageRunOptions(BaseModel):
    """Runtime knobs for one image-generation invocation."""

    max_retries: int = Field(default_factory=lambda: RetryConfig.MAX_RETRIES, ge=1)
    image_size: str = Field(default_factory=lambda: APIConfig.GEMINI_IMAGE_SIZE)
    aspect_ratio: str = "3:4"
    reference_mode: Literal["gemini_content", "none"] = "gemini_content"
    keyword_prompt_expansion: bool = True


class ImagePostRunOptions(BaseModel):
    """Route-level runtime options passed to specialist agents."""

    research: ResearchRunOptions = Field(default_factory=ResearchRunOptions)
    image: ImageRunOptions = Field(default_factory=ImageRunOptions)
    max_auto_images: int | None = Field(default_factory=lambda: ImageConfig.MAX_AUTO_IMAGES, ge=1)
    image_generation_concurrency: int = Field(default_factory=lambda: ImageConfig.GENERATION_CONCURRENCY, ge=1)


class ArticleResearchRunOptions(BaseModel):
    """Runtime knobs for one article research-agent invocation."""

    min_source_pages: int = Field(default_factory=lambda: ArticleResearchConfig.MIN_SOURCE_PAGES, ge=1)
    min_unique_domains: int = Field(default_factory=lambda: ArticleResearchConfig.MIN_UNIQUE_DOMAINS, ge=1)
    max_source_pages: int = Field(default_factory=lambda: ArticleResearchConfig.MAX_SOURCE_PAGES, ge=1)
    max_video_transcripts: int = Field(default_factory=lambda: ArticleResearchConfig.MAX_VIDEO_TRANSCRIPTS, ge=0)
    max_iterations: int = Field(default_factory=lambda: ArticleResearchConfig.MAX_ITERATIONS, ge=1)
    search_concurrency: int = Field(default_factory=lambda: ArticleResearchConfig.SEARCH_CONCURRENCY, ge=1)
    page_visit_concurrency: int = Field(default_factory=lambda: ArticleResearchConfig.PAGE_VISIT_CONCURRENCY, ge=1)
    max_tasks_per_iteration: int = Field(default_factory=lambda: ArticleResearchConfig.MAX_TASKS_PER_ITERATION, ge=1)
    min_curation_quality_score: float = Field(
        default_factory=lambda: ArticleResearchConfig.MIN_CURATION_QUALITY_SCORE,
        ge=0,
    )
    max_curated_sources_per_task: int = Field(
        default_factory=lambda: ArticleResearchConfig.MAX_CURATED_SOURCES_PER_TASK,
        ge=1,
    )
    max_curated_video_sources_per_task: int = Field(
        default_factory=lambda: ArticleResearchConfig.MAX_CURATED_VIDEO_SOURCES_PER_TASK,
        ge=1,
    )
    min_curated_sources_for_note_compression: int = Field(
        default_factory=lambda: ArticleResearchConfig.MIN_CURATED_SOURCES_FOR_NOTE_COMPRESSION,
        ge=1,
    )
    min_digests_for_full_synthesis: int = Field(
        default_factory=lambda: ArticleResearchConfig.MIN_DIGESTS_FOR_FULL_SYNTHESIS,
        ge=1,
    )
    include_mixed_video_queries: bool = Field(
        default_factory=lambda: ArticleResearchConfig.INCLUDE_MIXED_VIDEO_QUERIES,
    )
    video_max_filesize_mb: int = Field(
        default_factory=lambda: ArticleResearchConfig.VIDEO_MAX_FILESIZE_MB,
        ge=1,
    )


class ArticleContentRunOptions(BaseModel):
    """Runtime knobs for one article content-agent invocation."""

    max_iterations: int = Field(default_factory=lambda: ArticleContentConfig.MAX_ITERATIONS, ge=1)


class ArticleImageRunOptions(BaseModel):
    """Runtime knobs for one article image-agent invocation."""

    max_images: int = Field(default_factory=lambda: ArticleImageConfig.MAX_IMAGES, ge=1)


class ArticlePostRunOptions(BaseModel):
    """Route-level runtime options passed to article specialist agents."""

    research: ArticleResearchRunOptions = Field(default_factory=ArticleResearchRunOptions)
    content: ArticleContentRunOptions = Field(default_factory=ArticleContentRunOptions)
    image: ArticleImageRunOptions = Field(default_factory=ArticleImageRunOptions)
