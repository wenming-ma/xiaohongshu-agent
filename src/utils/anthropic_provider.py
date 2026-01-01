"""
Anthropic Model 工厂
提供带 HTTP 重试机制的共享 Model
"""
import os
from anthropic import AsyncAnthropic
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel


# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: AnthropicProvider | None = None


def get_anthropic_model(
    model_name: str = "claude-sonnet-4-20250514",
    max_retries: int = 10
) -> AnthropicModel:
    """
    获取配置好重试机制的 Anthropic Model

    Anthropic SDK 默认 max_retries=2，对于间歇性 502 错误可能不够。
    这里增加到 10 次，使用 SDK 内置的指数退避策略。

    重试条件（SDK 内置）：
    - 500+ 状态码（包括 502, 503, 504）
    - 408 请求超时
    - 409 锁冲突
    - 429 限流（会解析 Retry-After 头）

    Args:
        model_name: 模型名称（默认 claude-sonnet-4-20250514）
        max_retries: 最大重试次数（默认 10）

    Returns:
        AnthropicModel 实例
    """
    global _shared_provider

    if _shared_provider is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        # 创建带更多重试的 Anthropic 客户端
        client = AsyncAnthropic(
            api_key=api_key,
            max_retries=max_retries,
        )

        _shared_provider = AnthropicProvider(anthropic_client=client)

    # 使用共享的 Provider 创建 Model
    return AnthropicModel(model_name, provider=_shared_provider)
