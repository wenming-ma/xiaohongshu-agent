import importlib

from src.core.tool_registry import ToolRegistry
from src.tools.xiaohongshu import register_tools
import src.config.settings as settings_module


def teardown_function() -> None:
    ToolRegistry.clear()
    importlib.reload(settings_module)


def test_register_tools_only_exposes_implemented_xiaohongshu_tools() -> None:
    ToolRegistry.clear()

    register_tools()

    assert set(ToolRegistry._tools) == {
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
