"""
方法层重试装饰器
作为 HTTP 层 AsyncTenacityTransport 的兜底保障
"""
from functools import wraps
import asyncio

from pydantic_ai.exceptions import ModelHTTPError, ModelAPIError
from httpx import HTTPStatusError
from anthropic import APIConnectionError, APIStatusError

from ..config.settings import RetryConfig


# 可重试的异常类型
RETRYABLE_EXCEPTIONS = (
    # API 相关错误
    ModelHTTPError,      # pydantic-ai HTTP 错误
    ModelAPIError,       # pydantic-ai API 错误（含 Connection error）
    HTTPStatusError,     # httpx HTTP 状态错误
    APIConnectionError,  # anthropic 连接错误
    APIStatusError,      # anthropic 状态错误
    ConnectionError,     # 通用连接错误
    # 文件/下载相关错误
    TimeoutError,        # 下载超时
    FileNotFoundError,   # 文件未找到
)


def with_retry(max_retries: int = None, initial_delay: float = None):
    """
    异步重试装饰器（指数退避）

    作为 HTTP 层 AsyncTenacityTransport 的兜底：
    - HTTP 层重试单次 API 调用失败
    - 方法层重试整个工作流失败

    Args:
        max_retries: 最大重试次数，默认使用配置
        initial_delay: 初始延迟（秒），后续按 2^attempt 增长，默认使用配置

    Usage:
        @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
        async def my_func():
            ...
    """
    # 使用配置默认值
    if max_retries is None:
        max_retries = RetryConfig.MAX_RETRIES
    if initial_delay is None:
        initial_delay = RetryConfig.INITIAL_DELAY
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e
                    if attempt == max_retries:
                        raise
                    delay = initial_delay * (2 ** attempt)
                    error_type = type(e).__name__
                    print(f"   🔄 {error_type}，{delay:.0f}s 后重试整个工作流 ({attempt + 1}/{max_retries})...")
                    await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator
