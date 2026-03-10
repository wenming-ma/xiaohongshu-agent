"""
审核模型工厂
复用 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY 中转端点

用于所有文本审核任务（内容审核、研究数据审核、分组审核等）。
默认模型：claude-sonnet-4-6
"""
import os
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from ..config.settings import APIConfig


logger = logging.getLogger(__name__)

_shared_provider: AnthropicProvider | None = None


def get_review_model(model_name: str | None = None) -> AnthropicModel:
    """
    获取审核专用模型（Anthropic 中转端点）

    Args:
        model_name: 模型名称，默认 claude-sonnet-4-6

    Returns:
        AnthropicModel 实例
    """
    global _shared_provider
    model_name = model_name or APIConfig.REVIEW_MODEL

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
        logger.info("Review Provider 初始化完成: %s", base_url)

    return AnthropicModel(model_name, provider=_shared_provider)
