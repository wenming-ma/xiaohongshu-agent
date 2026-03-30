"""Xiaohongshu platform pipelines."""


def register_pipelines() -> None:
    """Register all implemented Xiaohongshu pipelines."""
    from ..core.pipeline_registry import PipelineRegistry
    from .article_post import XHSArticlePostPipeline
    from .image_post import XHSImagePostPipeline
    from .video_post import XHSVideoPostPipeline
    from .styled_image_post import StyledImagePostPipeline

    for pipeline_cls in (
        XHSArticlePostPipeline,
        XHSImagePostPipeline,
        XHSVideoPostPipeline,
        StyledImagePostPipeline,
    ):
        PipelineRegistry.register(pipeline_cls)
