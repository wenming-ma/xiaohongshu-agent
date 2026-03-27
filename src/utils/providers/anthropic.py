"""
Anthropic 中转模型工厂
复用 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY 环境变量
"""
import os
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv


def _ensure_legacy_anthropic_user_location() -> None:
    """
    兼容 anthropic==0.86.0：
    该版本缺少 `UserLocation` 导出，pydantic-ai 在导入时会抛 ImportError。
    这里在导入 pydantic-ai 之前补齐一个占位符，避免运行期崩溃。
    """
    try:
        from anthropic.types.beta import beta_web_search_tool_20250305_param as web_search_param
    except Exception:
        return

    if hasattr(web_search_param, "UserLocation"):
        return

    class UserLocation(dict):  # type: ignore[override]
        """Backward-compatible placeholder for pydantic-ai type import."""

    web_search_param.UserLocation = UserLocation


_ensure_legacy_anthropic_user_location()

from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel


logger = logging.getLogger(__name__)

_shared_provider: AnthropicProvider | None = None


def get_anthropic_model(model_name: str = "claude-sonnet-4-6") -> AnthropicModel:
    """
    获取 Anthropic 中转模型

    Args:
        model_name: 模型名称，默认 claude-sonnet-4-6

    Returns:
        AnthropicModel 实例
    """
    global _shared_provider

    if _shared_provider is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            load_dotenv()
            api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        base_url = os.getenv("ANTHROPIC_BASE_URL")

        client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=300.0,
            max_retries=20,
        )

        _shared_provider = AnthropicProvider(anthropic_client=client)
        logger.info("Anthropic Provider 初始化完成: %s", base_url)

    return AnthropicModel(model_name, provider=_shared_provider)
