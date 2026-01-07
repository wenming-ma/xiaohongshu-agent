"""
方法层重试装饰器
作为 HTTP 层 AsyncTenacityTransport 的兜底保障

遵循 pydantic-ai 官方最佳实践：
- 只重试暂时性错误（Rate limits、Network timeouts、Temporary API outages）
- 永久性错误（逻辑错误、验证错误）直接抛出并记录详细日志
"""
from functools import wraps
import asyncio
import traceback
import sys
from datetime import datetime

from pydantic_ai.exceptions import ModelHTTPError, ModelAPIError
from httpx import HTTPStatusError, TimeoutException, ConnectError, ReadError
from anthropic import APIConnectionError, APIStatusError

from ..config.settings import RetryConfig


# ==================== 暂时性错误（可重试）====================
# 这些错误是暂时的，重试后可能成功
TRANSIENT_EXCEPTIONS = (
    # pydantic-ai 错误
    ModelHTTPError,         # HTTP 层错误（如 429、5xx）
    ModelAPIError,          # API 错误（含 Connection error）
    
    # httpx 错误
    HTTPStatusError,        # HTTP 状态错误（如 429、5xx）
    TimeoutException,       # 请求超时
    ConnectError,           # 连接错误
    ReadError,              # 读取错误
    
    # anthropic SDK 错误
    APIConnectionError,     # 连接错误
    APIStatusError,         # 状态错误（如 429、5xx）
    
    # 通用网络错误
    ConnectionError,        # 通用连接错误
    TimeoutError,           # 通用超时错误
    OSError,                # 网络相关的 OS 错误（如 ECONNRESET）
)

# ==================== 永久性错误（不可重试）====================
# 这些错误是代码逻辑问题，重试不会解决
PERMANENT_EXCEPTIONS = (
    TypeError,              # 类型错误（代码逻辑问题）
    AttributeError,         # 属性错误（代码逻辑问题）
    ValueError,             # 值错误（参数问题）
    KeyError,               # 键错误（数据结构问题）
    IndexError,             # 索引错误（数据结构问题）
    ImportError,            # 导入错误（依赖问题）
    SyntaxError,            # 语法错误（代码问题）
    NameError,              # 名称错误（代码问题）
    AssertionError,         # 断言错误（逻辑问题）
)


def _format_exception_details(e: Exception, func_name: str, args: tuple, kwargs: dict) -> str:
    """格式化异常详细信息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 获取完整的堆栈信息
    exc_type, exc_value, exc_tb = sys.exc_info()
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    full_traceback = ''.join(tb_lines)
    
    # 格式化参数（截断过长的参数）
    def truncate(obj, max_len=200):
        s = repr(obj)
        return s[:max_len] + '...' if len(s) > max_len else s
    
    args_str = ', '.join(truncate(a) for a in args[:3])  # 只显示前3个位置参数
    kwargs_str = ', '.join(f'{k}={truncate(v)}' for k, v in list(kwargs.items())[:3])
    
    return f"""
{'='*60}
❌ 永久性错误 - 不可重试
{'='*60}
时间: {timestamp}
函数: {func_name}
参数: args=({args_str}), kwargs={{{kwargs_str}}}
异常类型: {type(e).__name__}
异常消息: {e}
{'='*60}
完整堆栈:
{full_traceback}
{'='*60}
"""


def _format_retry_info(e: Exception, func_name: str, attempt: int, max_retries: int, delay: float) -> str:
    """格式化重试信息"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"""   🔄 [{timestamp}] {type(e).__name__}: {e}
      函数: {func_name} | 重试: {attempt + 1}/{max_retries} | 等待: {delay:.1f}s"""


def with_retry(max_retries: int = None, initial_delay: float = None, max_total_wait: float = None):
    """
    异步重试装饰器（指数退避）
    
    遵循 pydantic-ai 官方最佳实践：
    - 只重试暂时性错误（网络/API 相关）
    - 永久性错误（逻辑错误）直接抛出并记录详细日志
    - 设置总等待时间上限，防止无限等待

    作为 HTTP 层 AsyncTenacityTransport 的兜底：
    - HTTP 层重试单次 API 调用失败
    - 方法层重试整个工作流失败

    Args:
        max_retries: 最大重试次数，默认使用配置
        initial_delay: 初始延迟（秒），后续按 2^attempt 增长，默认使用配置
        max_total_wait: 总最大等待时间（秒），超过后停止重试，默认使用配置

    Usage:
        @with_retry()
        async def my_func():
            ...
            
        @with_retry(max_retries=3, initial_delay=2.0)
        async def my_custom_func():
            ...
    """
    # 使用配置默认值
    if max_retries is None:
        max_retries = RetryConfig.MAX_RETRIES
    if initial_delay is None:
        initial_delay = RetryConfig.INITIAL_DELAY
    if max_total_wait is None:
        max_total_wait = RetryConfig.MAX_TOTAL_WAIT
        
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            total_wait_time = 0.0
            func_name = func.__name__
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except PERMANENT_EXCEPTIONS as e:
                    # 永久性错误：记录详细日志，直接抛出
                    error_details = _format_exception_details(e, func_name, args, kwargs)
                    print(error_details, file=sys.stderr)
                    raise
                    
                except TRANSIENT_EXCEPTIONS as e:
                    # 暂时性错误：可以重试
                    last_exception = e
                    
                    if attempt == max_retries:
                        print(f"\n   ❌ 重试次数耗尽 ({max_retries} 次)，最后错误: {type(e).__name__}: {e}")
                        raise
                    
                    # 计算延迟时间（指数退避，但不超过单次最大等待）
                    delay = min(initial_delay * (2 ** attempt), RetryConfig.HTTP_MAX_WAIT)
                    
                    # 检查是否超过总等待时间
                    if total_wait_time + delay > max_total_wait:
                        print(f"\n   ⏱️  总等待时间将超过上限 ({max_total_wait}s)，停止重试")
                        raise
                    
                    total_wait_time += delay
                    
                    # 打印重试信息
                    retry_info = _format_retry_info(e, func_name, attempt, max_retries, delay)
                    print(retry_info)
                    
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    # 未知异常：记录详细日志，直接抛出
                    error_details = _format_exception_details(e, func_name, args, kwargs)
                    print(error_details, file=sys.stderr)
                    print(f"\n   ⚠️  未知异常类型，不进行重试: {type(e).__name__}")
                    raise
                    
            raise last_exception
        return wrapper
    return decorator


def is_transient_error(e: Exception) -> bool:
    """检查异常是否为暂时性错误（可重试）"""
    return isinstance(e, TRANSIENT_EXCEPTIONS)


def is_permanent_error(e: Exception) -> bool:
    """检查异常是否为永久性错误（不可重试）"""
    return isinstance(e, PERMANENT_EXCEPTIONS)
