"""
MiniMax Model 工厂
提供带 HTTP 重试机制的共享 MiniMax Model

使用 pydantic-ai 的 Anthropic 兼容层（MiniMax 推荐方式）：
- MiniMax API 兼容 Anthropic 格式
- 支持 MiniMax-M2.1 模型
- 支持 Tool Use & Interleaved Thinking
- Base URL: https://api.minimax.io/anthropic
"""
import os
from httpx import AsyncClient, HTTPStatusError, Timeout
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from anthropic import AsyncAnthropic
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from ..config.settings import RetryConfig as AppRetryConfig, APIConfig


# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: AnthropicProvider | None = None


def _create_retrying_http_client() -> AsyncClient:
    """
    创建带智能重试的 HTTP 客户端

    使用 pydantic-ai 官方的 AsyncTenacityTransport：
    - 支持 Retry-After header（API 返回的等待时间）
    - 指数退避（fallback）
    - 配置来自 settings.py
    - 延长超时时间以适应 MiniMax API
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
    
    # MiniMax API 需要更长的超时时间（处理带工具的复杂请求）
    timeout = Timeout(
        connect=60.0,    # 连接超时
        read=300.0,      # 读取超时（5分钟，等待模型生成）
        write=60.0,      # 写入超时
        pool=60.0,       # 连接池超时
    )
    
    return AsyncClient(transport=transport, timeout=timeout)


def get_minimax_model(
    model_name: str = None
) -> AnthropicModel:
    """
    获取配置好重试机制的 MiniMax Model（使用 Anthropic 兼容 API）

    使用双层重试机制：
    - HTTP 层：AsyncTenacityTransport（支持 Retry-After，精细重试单次调用）
    - 方法层：@with_retry 装饰器（兜底重试整个工作流）

    Args:
        model_name: 模型名称，默认使用配置中的 MINIMAX_MODEL

    Returns:
        AnthropicModel 实例（使用 MiniMax Anthropic 兼容 API）
    """
    global _shared_provider
    model_name = model_name or APIConfig.MINIMAX_MODEL

    if _shared_provider is None:
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError("MINIMAX_API_KEY 环境变量未设置")

        # 创建带智能重试的 HTTP 客户端
        http_client = _create_retrying_http_client()

        # 创建 Anthropic 客户端（使用 MiniMax 的 Anthropic 兼容 base_url）
        # MiniMax 模型需要较长的超时时间（Interleaved Thinking 会消耗更多时间）
        client = AsyncAnthropic(
            api_key=api_key,
            base_url=APIConfig.MINIMAX_BASE_URL,
            http_client=http_client,
            timeout=300.0,  # 5分钟超时
            max_retries=10,  # SDK 内置重试次数
        )

        _shared_provider = AnthropicProvider(anthropic_client=client)

    # 使用共享的 Provider 创建 Model
    return AnthropicModel(model_name, provider=_shared_provider)
