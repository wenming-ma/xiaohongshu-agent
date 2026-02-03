"""
Anthropic Model 工厂
提供带 HTTP 重试机制和端点轮换的共享 Model

支持：
- HTTP 层智能重试（Retry-After header、指数退避）
- 端点轮换：当出现永久错误（额度不足、认证失败）时自动切换到下一个端点
"""
import os
import logging
from httpx import AsyncClient, HTTPStatusError
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from anthropic import AsyncAnthropic, AuthenticationError, PermissionDeniedError, RateLimitError
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from ..config.settings import RetryConfig as AppRetryConfig, APIConfig

logger = logging.getLogger(__name__)

# 当前端点索引（全局状态）
_current_endpoint_index: int = 0
# 缓存的 Provider 实例（按端点索引）
_providers: dict[int, AnthropicProvider] = {}

# 永久错误类型（需要轮换端点）
PERMANENT_ERROR_TYPES = (AuthenticationError, PermissionDeniedError)
PERMANENT_ERROR_MESSAGES = [
    "insufficient_quota", "quota_exceeded", "credit", "balance",
    "billing", "payment", "exceeded your current quota",
]


def is_permanent_error(error: Exception) -> bool:
    """判断是否为永久错误（需要轮换端点）"""
    if isinstance(error, PERMANENT_ERROR_TYPES):
        return True
    if isinstance(error, RateLimitError):
        msg = str(error).lower()
        return any(keyword in msg for keyword in PERMANENT_ERROR_MESSAGES)
    return False


def rotate_endpoint() -> bool:
    """
    轮换到下一个端点
    Returns: True 如果成功轮换，False 如果已经轮换一圈回到起点
    """
    global _current_endpoint_index
    endpoints = APIConfig.ANTHROPIC_ENDPOINTS
    if not endpoints:
        return False

    old_index = _current_endpoint_index
    _current_endpoint_index = (_current_endpoint_index + 1) % len(endpoints)

    new_endpoint = endpoints[_current_endpoint_index]
    base_url = new_endpoint.get("base_url") or "官方API"
    logger.warning(f"端点轮换: {old_index} -> {_current_endpoint_index} ({base_url})")

    return _current_endpoint_index != old_index or len(endpoints) == 1


def get_current_endpoint_info() -> dict:
    """获取当前端点信息"""
    endpoints = APIConfig.ANTHROPIC_ENDPOINTS
    if not endpoints:
        return {"base_url": None, "api_key_env": "ANTHROPIC_API_KEY"}
    return endpoints[_current_endpoint_index]


def _get_api_key(endpoint: dict) -> str:
    """从端点配置获取 API key"""
    if "api_key" in endpoint:
        return endpoint["api_key"]
    env_var = endpoint.get("api_key_env", "ANTHROPIC_API_KEY")
    key = os.getenv(env_var)
    if not key:
        raise ValueError(f"{env_var} 环境变量未设置")
    return key


def _create_retrying_http_client() -> AsyncClient:
    """创建带智能重试的 HTTP 客户端"""
    def should_retry_status(response):
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


def _create_provider_for_endpoint(endpoint: dict) -> AnthropicProvider:
    """为指定端点创建 Provider"""
    api_key = _get_api_key(endpoint)
    base_url = endpoint.get("base_url")
    http_client = _create_retrying_http_client()

    client = AsyncAnthropic(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        max_retries=10,
    )

    return AnthropicProvider(anthropic_client=client)


def get_anthropic_model(model_name: str = None) -> AnthropicModel:
    """
    获取配置好重试机制的 Anthropic Model

    使用当前端点创建 Model。如果遇到永久错误，调用 rotate_endpoint() 后重新获取。
    """
    global _providers
    model_name = model_name or APIConfig.DEFAULT_MODEL

    if _current_endpoint_index not in _providers:
        endpoint = get_current_endpoint_info()
        _providers[_current_endpoint_index] = _create_provider_for_endpoint(endpoint)
        base_url = endpoint.get("base_url") or "官方API"
        logger.info(f"使用端点 {_current_endpoint_index}: {base_url}")

    return AnthropicModel(model_name, provider=_providers[_current_endpoint_index])


def handle_permanent_error(error: Exception) -> bool:
    """
    处理永久错误，尝试轮换端点

    Returns: True 如果成功轮换到新端点，False 如果无法轮换
    """
    if not is_permanent_error(error):
        return False

    logger.warning(f"检测到永久错误: {type(error).__name__}: {error}")
    return rotate_endpoint()
