"""
OpenAI 模型工厂
使用 OpenAI Chat Completions API，支持自定义 base_url
"""
import os
import logging
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIChatModel
from ...config.settings import APIConfig


logger = logging.getLogger(__name__)

_shared_provider: OpenAIProvider | None = None


def get_openai_model(
    model_name: str = None,
) -> OpenAIChatModel:
    """
    获取配置好的 OpenAI Model（使用 Chat Completions API）

    Args:
        model_name: 模型名称，默认使用配置中的 OPENAI_MODEL

    Returns:
        OpenAIChatModel 实例
    """
    global _shared_provider
    model_name = model_name or APIConfig.OPENAI_MODEL

    if _shared_provider is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY 环境变量未设置")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=APIConfig.OPENAI_BASE_URL,
            timeout=300.0,
            max_retries=20,
        )

        _shared_provider = OpenAIProvider(openai_client=client)
        logger.info(f"OpenAI Provider 初始化完成: {APIConfig.OPENAI_BASE_URL}")

    return OpenAIChatModel(model_name, provider=_shared_provider)


def reset_provider():
    """重置共享的 Provider 实例（用于测试或配置更新后）"""
    global _shared_provider
    _shared_provider = None
    logger.info("OpenAI Provider 已重置")
