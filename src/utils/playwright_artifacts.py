from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..config.settings import PathConfig
from .logger import get_logger

if TYPE_CHECKING:
    from pydantic_ai.mcp import MCPServerStdio

logger = get_logger(__name__)

_GUARD_MARKER = "_playwright_artifact_guard_installed"
_FILENAME_TOOLS = {
    "browser_take_screenshot",
    "browser_console_messages",
    "browser_network_requests",
    "browser_snapshot",
}


def sanitize_playwright_filename(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in _FILENAME_TOOLS:
        return tool_args

    raw_filename = tool_args.get("filename")
    if not isinstance(raw_filename, str) or not raw_filename.strip():
        return tool_args

    filename = raw_filename.replace("\\", "/").rstrip("/").split("/")[-1]
    if not filename:
        return tool_args

    if tool_name == "browser_take_screenshot" and not Path(filename).suffix:
        screenshot_type = str(tool_args.get("type") or "png").lower()
        filename = f"{filename}.jpeg" if screenshot_type == "jpeg" else f"{filename}.png"

    if filename == raw_filename:
        return tool_args

    logger.info(
        "Sanitized Playwright artifact filename for %s: %s -> %s",
        tool_name,
        raw_filename,
        filename,
    )
    return {
        **tool_args,
        "filename": filename,
    }


def install_playwright_artifact_guard(mcp_server: "MCPServerStdio") -> None:
    if getattr(mcp_server, _GUARD_MARKER, False):
        return

    PathConfig.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    existing = getattr(mcp_server, "process_tool_call", None)

    async def wrapped(ctx, call_tool, name: str, args: dict[str, Any]):
        normalized_args = args
        if isinstance(args, dict):
            normalized_args = sanitize_playwright_filename(name, args)

        if existing is not None:
            return await existing(ctx, call_tool, name, normalized_args)
        return await call_tool(name, normalized_args, None)

    mcp_server.process_tool_call = wrapped
    setattr(mcp_server, _GUARD_MARKER, True)
