"""
统一模型工厂
根据配置选择使用 Anthropic、OpenRouter 或 MiniMax 作为模型提供者

支持的提供者：
- anthropic: 使用 Anthropic API 直连 Claude 模型
- openrouter: 使用 OpenRouter 中转，支持多种模型（GLM, Claude, GPT 等）
- minimax: 使用 MiniMax API（OpenAI 兼容格式），支持 MiniMax-Text-01、abab 系列模型
"""
from pydantic_ai.models import Model
from ..config.settings import APIConfig


def get_model(model_name: str = None) -> Model:
    """
    获取配置好的 AI 模型

    根据 APIConfig.MODEL_PROVIDER 配置选择使用 Anthropic、OpenRouter 或 MiniMax。

    Args:
        model_name: 模型名称，如不指定则使用配置中的默认值

    Returns:
        Model 实例（AnthropicModel、OpenRouterModel 或 OpenAIChatModel）

    Raises:
        ValueError: 如果配置的 MODEL_PROVIDER 不支持
    """
    provider = APIConfig.MODEL_PROVIDER.lower()

    if provider == "anthropic":
        from .anthropic_provider import get_anthropic_model
        return get_anthropic_model(model_name)

    elif provider == "openrouter":
        from .openrouter_provider import get_openrouter_model
        return get_openrouter_model(model_name)

    elif provider == "minimax":
        from .minimax_provider import get_minimax_model
        return get_minimax_model(model_name)

    else:
        raise ValueError(
            f"不支持的模型提供者: {provider}。"
            f"请在 settings.py 中将 MODEL_PROVIDER 设置为 'anthropic'、'openrouter' 或 'minimax'"
        )
