"""Xiaohongshu platform pipelines."""

from ..core.pipeline_registry import PipelineRegistry
from .article_post import XHSArticlePostPipeline
from .image_post import XHSImagePostPipeline
from .video_post import XHSVideoPostPipeline
from .styled_image_post import StyledImagePostPipeline

IMPLEMENTED_PIPELINES = (
    XHSArticlePostPipeline,
    XHSImagePostPipeline,
    XHSVideoPostPipeline,
    StyledImagePostPipeline,
)


def register_pipelines() -> None:
    """Register all implemented Xiaohongshu pipelines."""
    for pipeline_cls in IMPLEMENTED_PIPELINES:
        PipelineRegistry.register(pipeline_cls)


__all__ = [
    "IMPLEMENTED_PIPELINES",
    "XHSArticlePostPipeline",
    "XHSImagePostPipeline",
    "XHSVideoPostPipeline",
    "StyledImagePostPipeline",
    "register_pipelines",
]
