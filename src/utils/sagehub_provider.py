"""
SageHub Provider (Claude 中转服务)
提供带 HTTP 重试机制的共享 SageHub Model

使用 pydantic-ai 的 OpenAI 兼容层：
- SageHub 使用 OpenAI 兼容 API 格式
- 支持 Claude 4.5 系列模型（Opus, Sonnet, Haiku）
- 所有模型都支持视觉功能
- Base URL: https://api.sagehub.cc/v1
"""
import os
from httpx import AsyncClient, HTTPStatusError, Timeout
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from ..config.settings import RetryConfig as AppRetryConfig, APIConfig


# 全局共享的客户端实例（避免重复创建）
_shared_client: AsyncOpenAI | None = None


def _create_retrying_http_client() -> AsyncClient:
    """
    创建带智能重试的 HTTP 客户端

    使用 pydantic-ai 官方的 AsyncTenacityTransport：
    - 支持 Retry-After header（API 返回的等待时间）
    - 指数退避（fallback）
    - 配置来自 settings.py
    """
    def should_retry_status(response):
        """检查响应状态码，决定是否重试"""
        if response.status_code in APIConfig.RETRYABLE_STATUS_CODES:
            response.raise_for_status()

    transport = AsyncTenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
            wait=wait_retry_after(
                fallback_strategy=wait_exponential(multiplier=1, max=AppRetryConfig.HTTP_MAX_WAIT),
                max_wait=AppRetryConfig.HTTP_TOTAL_MAX_WAIT
            ),
            stop=stop_after_attempt(AppRetryConfig.HTTP_MAX_RETRIES),
            reraise=True
        ),
        validate_response=should_retry_status
    )

    # SageHub 超时配置
    timeout = Timeout(
        connect=60.0,    # 连接超时
        read=300.0,      # 读取超时（5分钟，视觉模型处理时间较长）
        write=60.0,      # 写入超时
        pool=60.0,       # 连接池超时
    )

    return AsyncClient(transport=transport, timeout=timeout)


def get_sagehub_model(
    model_name: str = None
) -> OpenAIChatModel:
    """
    获取配置好的 SageHub Model（使用 OpenAI 兼容 API）

    注意：OpenAIChatModel 会通过环境变量获取配置：
    - OPENAI_API_KEY: API 密钥（我们用 SAGEHUB_API_KEY）
    - OPENAI_BASE_URL: Base URL

    Args:
        model_name: 模型名称，默认使用配置中的 SAGEHUB_MODEL

    Returns:
        OpenAIChatModel 实例
    """
    model_name = model_name or APIConfig.SAGEHUB_MODEL

    api_key = os.getenv("SAGEHUB_API_KEY")
    if not api_key:
        raise ValueError("SAGEHUB_API_KEY 环境变量未设置")

    # 临时设置 OPENAI_ 环境变量，让 OpenAIChatModel 使用
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = APIConfig.SAGEHUB_BASE_URL

    # 创建 Model（会自动使用环境变量）
    return OpenAIChatModel(model_name)
