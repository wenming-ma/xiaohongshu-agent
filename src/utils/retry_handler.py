"""
最简单的异步重试装饰器
参考 LangGraph/CrewAI 的指数退避模式
"""
from functools import wraps
import asyncio

from pydantic_ai.exceptions import ModelHTTPError


def with_retry(max_retries: int = 3, initial_delay: float = 2.0):
    """
    异步重试装饰器（指数退避）

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒），后续按 2^attempt 增长

    Usage:
        @with_retry(max_retries=3, initial_delay=5.0)
        async def my_func():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except ModelHTTPError as e:
                    # 只重试 5xx 和 429 错误
                    if e.status_code not in (500, 502, 503, 504, 429):
                        raise
                    if attempt == max_retries:
                        raise
                    delay = initial_delay * (2 ** attempt)
                    print(f"   🔄 API 错误 ({e.status_code})，{delay:.0f}s 后重试 ({attempt + 1}/{max_retries})...")
                    await asyncio.sleep(delay)
        return wrapper
    return decorator
