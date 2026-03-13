"""Xiaohongshu platform tools."""

from ...core.tool_registry import ToolRegistry
from .article_post import XHSArticlePostTool
from .image_post import XHSImagePostTool
from .video_post import XHSVideoPostTool

IMPLEMENTED_TOOLS = (
    XHSArticlePostTool,
    XHSImagePostTool,
    XHSVideoPostTool,
)


def register_tools() -> None:
    """Register all implemented Xiaohongshu tools."""
    for tool_cls in IMPLEMENTED_TOOLS:
        ToolRegistry.register(tool_cls)


__all__ = [
    "IMPLEMENTED_TOOLS",
    "XHSArticlePostTool",
    "XHSImagePostTool",
    "XHSVideoPostTool",
    "register_tools",
]
