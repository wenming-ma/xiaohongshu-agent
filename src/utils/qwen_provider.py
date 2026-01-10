"""
Qwen Model 工厂（阿里云通义千问）
提供带 HTTP 重试机制的共享 Qwen Model

使用 pydantic-ai 的 OpenAI 兼容层：
- Qwen API 兼容 OpenAI 格式
- 支持视觉模型：qwen-vl-plus, qwen-vl-max
- Base URL: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
"""
import os
from httpx import AsyncClient, HTTPStatusError, Timeout
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIModel
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

    # Qwen API 超时配置
    timeout = Timeout(
        connect=60.0,    # 连接超时
        read=300.0,      # 读取超时（5分钟，视觉模型处理时间较长）
        write=60.0,      # 写入超时
        pool=60.0,       # 连接池超时
    )

    return AsyncClient(transport=transport, timeout=timeout)


def get_qwen_model(
    model_name: str = None
) -> OpenAIModel:
    """
    获取配置好重试机制的 Qwen Model（使用 OpenAI 兼容 API）

    使用双层重试机制：
    - HTTP 层：AsyncTenacityTransport（支持 Retry-After，精细重试单次调用）
    - 方法层：@with_retry 装饰器（兜底重试整个工作流）

    Args:
        model_name: 模型名称，默认使用配置中的 QWEN_MODEL

    Returns:
        OpenAIModel 实例（使用 Qwen OpenAI 兼容 API）
    """
    global _shared_client
    model_name = model_name or APIConfig.QWEN_MODEL

    if _shared_client is None:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY 环境变量未设置")

        # 创建带智能重试的 HTTP 客户端
        http_client = _create_retrying_http_client()

        # 创建 OpenAI 客户端（使用 Qwen 的 base_url）
        _shared_client = AsyncOpenAI(
            api_key=api_key,
            base_url=APIConfig.QWEN_BASE_URL,
            http_client=http_client,
            timeout=300.0,  # 5分钟超时
        )

    # 使用共享的客户端创建 Model
    return OpenAIModel(model_name, openai_client=_shared_client)
