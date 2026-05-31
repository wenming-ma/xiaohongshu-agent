from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.config.settings import APIConfig, ImageConfig, ResearchConfig, RetryConfig


class ResearchRunOptions(BaseModel):
    """Runtime knobs for one research-agent invocation."""

    min_posts_researched: int = Field(default_factory=lambda: ResearchConfig.MIN_POSTS_RESEARCHED, ge=1)
    validation_max_retries: int = Field(default_factory=lambda: ResearchConfig.VALIDATION_MAX_RETRIES, ge=1)
    min_key_infos: int = Field(default_factory=lambda: ResearchConfig.MIN_KEY_INFOS, ge=1)
    min_cases: int = Field(default_factory=lambda: ResearchConfig.MIN_CASES, ge=0)


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
