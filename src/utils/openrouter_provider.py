"""
OpenRouter Model 工厂
提供带 HTTP 重试机制的共享 OpenRouter Model

使用 pydantic-ai 官方的 OpenRouterProvider 和 OpenRouterModel：
- 支持多种模型提供商（OpenAI, Claude, Gemini, GLM 等）
- 支持 OpenRouter 特有功能（推理 token、provider 路由等）
"""
import os
from httpx import AsyncClient, HTTPStatusError
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from ..config.settings import RetryConfig as AppRetryConfig, APIConfig


# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: OpenRouterProvider | None = None


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
    return AsyncClient(transport=transport)


def get_openrouter_model(
    model_name: str = None
) -> OpenRouterModel:
    """
    获取配置好重试机制的 OpenRouter Model

    使用双层重试机制：
    - HTTP 层：AsyncTenacityTransport（支持 Retry-After，精细重试单次调用）
    - 方法层：@with_retry 装饰器（兜底重试整个工作流）

    Args:
        model_name: 模型名称，默认使用配置中的 OPENROUTER_MODEL

    Returns:
        OpenRouterModel 实例
    """
    global _shared_provider
    model_name = model_name or APIConfig.OPENROUTER_MODEL

    if _shared_provider is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY 环境变量未设置")

        # 创建带智能重试的 HTTP 客户端
        http_client = _create_retrying_http_client()

        # 创建 OpenRouter Provider（使用自定义 HTTP 客户端）
        _shared_provider = OpenRouterProvider(
            api_key=api_key,
            http_client=http_client,
            app_title="xiaohongshu-agent",  # 可选：用于 OpenRouter 统计
        )

    # 使用共享的 Provider 创建 Model
    return OpenRouterModel(model_name, provider=_shared_provider)
