"""Shared Xiaohongshu tool capabilities."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BodyInjectTool",
    "build_shared_playwright_mcp_args",
    "build_shared_playwright_mcp_env",
    "create_shared_playwright_mcp_server",
]


def __getattr__(name: str) -> Any:
    if name == "BodyInjectTool":
        return import_module(".body_inject", __name__).BodyInjectTool
    if name in {
        "build_shared_playwright_mcp_args",
        "build_shared_playwright_mcp_env",
        "create_shared_playwright_mcp_server",
    }:
        module = import_module(".playwright", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
