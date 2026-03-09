"""Xiaohongshu platform tools."""

from ...core.tool_registry import ToolRegistry
from .image_post import XHSImagePostTool
from .video_post import XHSVideoPostTool

IMPLEMENTED_TOOLS = (
    XHSImagePostTool,
    XHSVideoPostTool,
)


def register_tools() -> None:
    """Register all implemented Xiaohongshu tools."""
    for tool_cls in IMPLEMENTED_TOOLS:
        ToolRegistry.register(tool_cls)


__all__ = [
    "IMPLEMENTED_TOOLS",
    "XHSImagePostTool",
    "XHSVideoPostTool",
    "register_tools",
]
