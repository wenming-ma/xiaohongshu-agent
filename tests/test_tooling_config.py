import importlib

from src.core.tool_registry import ToolRegistry
from src.tools.xiaohongshu.shared import (
    build_shared_playwright_mcp_args,
    build_shared_playwright_mcp_env,
)
from src.tools.xiaohongshu import register_tools
import src.config.settings as settings_module


def teardown_function() -> None:
    ToolRegistry.clear()
    importlib.reload(settings_module)


def test_register_tools_only_exposes_implemented_xiaohongshu_tools() -> None:
    ToolRegistry.clear()

    register_tools()

    assert set(ToolRegistry._tools) == {
        "xiaohongshu_article_post",
        "xiaohongshu_image_post",
        "xiaohongshu_video_post",
    }


def test_api_config_defaults_do_not_embed_credentials(monkeypatch) -> None:
    for env_name in (
        "ANTHROPIC_ENDPOINTS_JSON",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_FALLBACK_BASE_URL",
        "ANTHROPIC_FALLBACK_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_FALLBACK_API_KEYS",
    ):
        monkeypatch.delenv(env_name, raising=False)

    settings = importlib.reload(settings_module)

    assert settings.APIConfig.ANTHROPIC_ENDPOINTS == [
        {"api_key_env": "ANTHROPIC_API_KEY"},
    ]
    assert settings.APIConfig.GEMINI_API_KEY is None
    assert settings.APIConfig.GEMINI_FALLBACK_API_KEYS == []


def test_shared_playwright_mcp_uses_shared_browser_session() -> None:
    settings = importlib.reload(settings_module)

    args = build_shared_playwright_mcp_args()
    env = build_shared_playwright_mcp_env()

    assert "--user-data-dir" in args
    assert args[args.index("--user-data-dir") + 1] == str(settings.PathConfig.BROWSER_SESSION_SHARED)
    assert env["USER_DATA_DIR"] == str(settings.PathConfig.BROWSER_SESSION_SHARED)
