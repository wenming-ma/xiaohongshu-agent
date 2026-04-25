import importlib

from src.core.pipeline_registry import PipelineRegistry
from src.agents.shared import (
    build_shared_playwright_mcp_args,
    build_shared_playwright_mcp_env,
)
from src.agents import register_pipelines
import src.config.settings as settings_module


def teardown_function() -> None:
    PipelineRegistry.clear()
    importlib.reload(settings_module)


def test_register_pipelines_only_exposes_implemented_xiaohongshu_pipelines() -> None:
    PipelineRegistry.clear()

    register_pipelines()

    assert set(PipelineRegistry._pipelines) == {
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


def test_api_config_defaults_openai_model_to_gpt_5_4(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    settings = importlib.reload(settings_module)

    assert settings.APIConfig.OPENAI_MODEL == "gpt-5.4"


def test_shared_playwright_mcp_uses_shared_browser_session() -> None:
    settings = importlib.reload(settings_module)

    args = build_shared_playwright_mcp_args()
    env = build_shared_playwright_mcp_env()

    assert "--user-data-dir" in args
    assert args[args.index("--user-data-dir") + 1] == str(settings.PathConfig.BROWSER_SESSION_SHARED)
    assert env["USER_DATA_DIR"] == str(settings.PathConfig.BROWSER_SESSION_SHARED)
