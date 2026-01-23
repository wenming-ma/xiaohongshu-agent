"""
MiniMax Model 工厂
提供带 HTTP 重试机制的共享 MiniMax Model

使用 pydantic-ai 的 Anthropic 兼容层（通过 Nexus 代理访问）：
- Nexus 代理使用 Anthropic 兼容格式，但用 Bearer token 认证
- 支持 MiniMax-M2.1 模型
- 支持 Tool Use & Interleaved Thinking
- Base URL: https://nexus.itssx.com/api/claude_code/cc_minimax21
"""
import os
import logging
from httpx import AsyncClient, HTTPStatusError, Timeout, Request, Response, AsyncBaseTransport, AsyncHTTPTransport
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from anthropic import AsyncAnthropic
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.retries import RetryConfig, wait_retry_after
from ..config.settings import RetryConfig as AppRetryConfig, APIConfig


logger = logging.getLogger(__name__)

# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: AnthropicProvider | None = None


class BearerAuthTransport(AsyncBaseTransport):
    """
    Transport 层拦截，将 x-api-key 替换为 Authorization: Bearer

    这比 httpx.Auth 更可靠，因为它在请求发送前直接修改 headers。
    Nexus 代理要求使用 Bearer token 认证，而 Anthropic SDK 总是使用 x-api-key。
    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._transport = AsyncHTTPTransport()
        self._request_count = 0

    async def handle_async_request(self, request: Request) -> Response:
        self._request_count += 1
        request_id = self._request_count

        # 直接修改请求的 headers（原地修改，不创建新请求）
        if "x-api-key" in request.headers:
            del request.headers["x-api-key"]
        request.headers["Authorization"] = f"Bearer {self._api_key}"

        # 计算请求大小（用于调试）
        content_length = request.headers.get("content-length", "unknown")
        logger.debug(f"[Request #{request_id}] URL: {request.url}, Size: {content_length} bytes")

        try:
            response = await self._transport.handle_async_request(request)
            logger.debug(f"[Request #{request_id}] Response: {response.status_code}")
            return response
        except Exception as e:
            logger.warning(f"[Request #{request_id}] Error: {type(e).__name__}: {str(e)[:100]}")
            raise

    async def aclose(self) -> None:
        await self._transport.aclose()


def _create_http_client(api_key: str) -> AsyncClient:
    """
    创建带 Bearer token 认证的 HTTP 客户端

    使用 BearerAuthTransport 在 transport 层直接修改 headers，
    比 httpx.Auth 更可靠。
    """
    # MiniMax API 需要更长的超时时间（处理带工具的复杂请求）
    timeout = Timeout(
        connect=60.0,    # 连接超时
        read=300.0,      # 读取超时（5分钟，等待模型生成）
        write=60.0,      # 写入超时
        pool=60.0,       # 连接池超时
    )

    return AsyncClient(
        transport=BearerAuthTransport(api_key),
        timeout=timeout,
    )


def get_minimax_model(
    model_name: str = None
) -> AnthropicModel:
    """
    获取配置好的 MiniMax Model（使用 Anthropic 兼容 API）

    注意：Nexus 代理使用 Bearer token 认证而非标准的 x-api-key

    Args:
        model_name: 模型名称，默认使用配置中的 MINIMAX_MODEL

    Returns:
        AnthropicModel 实例（使用 Nexus 代理的 Anthropic 兼容 API）
    """
    global _shared_provider
    model_name = model_name or APIConfig.MINIMAX_MODEL

    if _shared_provider is None:
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError("MINIMAX_API_KEY 环境变量未设置")

        # 创建带 Bearer token 认证的 HTTP 客户端
        http_client = _create_http_client(api_key)

        # 创建 Anthropic 客户端
        # api_key 设置为 placeholder，认证通过 BearerAuthTransport 实现
        # max_retries 设为较高值，因为 Nexus 代理可能有波动
        client = AsyncAnthropic(
            api_key="placeholder",
            base_url=APIConfig.MINIMAX_BASE_URL,
            http_client=http_client,
            timeout=300.0,  # 5分钟超时
            max_retries=20,  # SDK 内置重试次数增加到 20
        )

        _shared_provider = AnthropicProvider(anthropic_client=client)
        logger.info(f"MiniMax Provider 初始化完成: {APIConfig.MINIMAX_BASE_URL}")

    # 使用共享的 Provider 创建 Model
    return AnthropicModel(model_name, provider=_shared_provider)


def reset_provider():
    """重置共享的 Provider 实例（用于测试或配置更新后）"""
    global _shared_provider
    _shared_provider = None
    logger.info("MiniMax Provider 已重置")
