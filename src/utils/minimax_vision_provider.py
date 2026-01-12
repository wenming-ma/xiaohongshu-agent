"""
MiniMax Vision Provider
提供带 HTTP 重试机制的 MiniMax 视觉模型

使用 pydantic-ai 的 OpenAI 兼容层：
- MiniMax 视觉 API 使用 OpenAI 兼容格式
- 端点: https://api.minimax.io/v1/chat/completions
- 支持模型: MiniMax-Text-01, minimax-visual-turbo
- 支持图片格式: JPEG, PNG, GIF, WebP (最大 20MB)
"""
import os
from httpx import AsyncClient, HTTPStatusError, Timeout
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from ..config.settings import RetryConfig as AppRetryConfig, APIConfig


# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: OpenAIProvider | None = None

# MiniMax 视觉 API 配置
MINIMAX_VISION_BASE_URL = "https://api.minimax.io/v1"
MINIMAX_VISION_MODEL = "MiniMax-Text-01"  # 支持视觉的模型


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

    # MiniMax 视觉模型需要较长的超时时间
    timeout = Timeout(
        connect=60.0,    # 连接超时
        read=300.0,      # 读取超时（5分钟，视觉模型处理时间较长）
        write=60.0,      # 写入超时
        pool=60.0,       # 连接池超时
    )

    return AsyncClient(transport=transport, timeout=timeout)


def get_minimax_vision_model(
    model_name: str = None
) -> OpenAIChatModel:
    """
    获取配置好的 MiniMax Vision Model（使用 OpenAI 兼容 API）

    MiniMax 视觉 API 支持：
    - 图片 URL 输入
    - Base64 编码图片输入
    - 支持格式: JPEG, PNG, GIF, WebP (最大 20MB)

    Args:
        model_name: 模型名称，默认使用 MiniMax-Text-01

    Returns:
        OpenAIChatModel 实例
    """
    global _shared_provider
    model_name = model_name or MINIMAX_VISION_MODEL

    if _shared_provider is None:
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError("MINIMAX_API_KEY 环境变量未设置")

        # 创建带智能重试的 HTTP 客户端
        http_client = _create_retrying_http_client()

        # 创建 OpenAI 兼容 Provider（使用 MiniMax 视觉 API）
        _shared_provider = OpenAIProvider(
            base_url=MINIMAX_VISION_BASE_URL,
            api_key=api_key,
            http_client=http_client,
        )

    # 创建 Model（使用共享 Provider）
    return OpenAIChatModel(model_name, provider=_shared_provider)
