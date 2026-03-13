"""Shared Playwright MCP server factory for Xiaohongshu tools."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.mcp import MCPServerStdio

from ....config.settings import PathConfig, RetryConfig, TimeoutConfig
from ....utils.playwright_artifacts import install_playwright_artifact_guard


def build_shared_playwright_mcp_args(output_dir: Path | None = None) -> list[str]:
    session_dir = str(Path(PathConfig.BROWSER_SESSION_SHARED))
    artifacts_dir = str(Path(output_dir or PathConfig.DOWNLOADS_DIR))
    return [
        "-y",
        "@playwright/mcp@latest",
        "--browser",
        "chrome",
        "--user-data-dir",
        session_dir,
        "--output-dir",
        artifacts_dir,
    ]


def build_shared_playwright_mcp_env(*, headless: bool = False) -> dict[str, str]:
    return {
        "HEADLESS": "true" if headless else "false",
        "BROWSER_TYPE": "chrome",
        "USER_DATA_DIR": str(Path(PathConfig.BROWSER_SESSION_SHARED)),
    }


def create_shared_playwright_mcp_server(
    *,
    output_dir: Path | None = None,
    tool_prefix: str = "playwright",
    headless: bool = False,
) -> MCPServerStdio:
    artifacts_dir = Path(output_dir or PathConfig.DOWNLOADS_DIR)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    server = MCPServerStdio(
        command="npx",
        args=build_shared_playwright_mcp_args(output_dir),
        env=build_shared_playwright_mcp_env(headless=headless),
        cwd=str(artifacts_dir),
        tool_prefix=tool_prefix,
        cache_tools=True,
        max_retries=RetryConfig.MCP_RETRIES,
        timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
    )
    install_playwright_artifact_guard(server)
    return server
