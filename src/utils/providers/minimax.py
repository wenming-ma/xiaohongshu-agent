"""
MiniMax Model 工厂
提供带 HTTP 重试机制的共享 MiniMax Model

使用 pydantic-ai 的 Anthropic 兼容层（MiniMax 官方 Anthropic 端点）：
- 支持 MiniMax-M2.7 模型
- 支持 Tool Use & Interleaved Thinking
- Base URL: https://api.minimax.io/anthropic
"""
import os
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from ...config.settings import APIConfig


logger = logging.getLogger(__name__)

# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: AnthropicProvider | None = None


def get_minimax_model(
    model_name: str = None
) -> AnthropicModel:
    """
    获取配置好的 MiniMax Model（使用 Anthropic 兼容 API）

    Args:
        model_name: 模型名称，默认使用配置中的 MINIMAX_MODEL

    Returns:
        AnthropicModel 实例
    """
    global _shared_provider
    model_name = model_name or APIConfig.MINIMAX_MODEL

    if _shared_provider is None:
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            load_dotenv()
            api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError("MINIMAX_API_KEY 环境变量未设置")

        client = AsyncAnthropic(
            api_key=api_key,
            base_url=APIConfig.MINIMAX_ANTHROPIC_BASE_URL,
            timeout=300.0,
            max_retries=20,
        )

        _shared_provider = AnthropicProvider(anthropic_client=client)
        logger.info(
            "MiniMax Provider 初始化完成(anthropic): %s",
            APIConfig.MINIMAX_ANTHROPIC_BASE_URL,
        )

    return AnthropicModel(model_name, provider=_shared_provider)


def reset_provider():
    """重置共享的 Provider 实例（用于测试或配置更新后）"""
    global _shared_provider
    _shared_provider = None
    logger.info("MiniMax Provider 已重置")
