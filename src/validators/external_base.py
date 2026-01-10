"""
外部验证器基类（装饰器模式）
验证失败时重试整个函数

子类只需实现：
- validator_name: 验证器名称（用于日志）
- validate(): 验证逻辑
- get_validation_target(): 从函数结果中提取验证目标

依赖注入机制：
- 验证失败时，会尝试更新 kwargs 中的 gen_ctx.validation_feedback
- 提示词生成 Agent 的动态 system_prompt 会读取该反馈并调整提示词
"""
from abc import ABC, abstractmethod
from functools import wraps
import asyncio
from typing import Any, Callable, TypeVar
import logfire
from ..utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class ValidationError(Exception):
    """验证失败异常"""

    def __init__(self, issues: list):
        self.issues = issues
        super().__init__(f"验证失败: {', '.join(issues)}")


class ExternalValidator(ABC):
    """
    外部验证器基类 - 作为装饰器使用

    特点：
    - 装饰器模式，在函数外部执行验证
    - 验证失败时重试整个函数
    - 适用于图片生成等可重试的场景

    Usage:
        @GeminiConfigValidator(max_retries=3)
        @ImageQualityValidator(max_retries=2)
        async def _generate_via_gemini(self, prompt, output_dir, image_type):
            ...
    """

    def __init__(self, max_retries: int = 3, initial_delay: float = 5.0):
        """
        初始化验证器

        Args:
            max_retries: 验证失败时的最大重试次数
            initial_delay: 初始延迟（秒），按 2^attempt 指数退避
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self._agent = None  # 延迟初始化
        self._temp_screenshot = None  # 临时截屏路径（验证通过后删除）

    @property
    @abstractmethod
    def validator_name(self) -> str:
        """验证器名称（用于日志显示）"""
        pass

    @abstractmethod
    async def validate(self, target: Any, context: dict) -> Any:
        """
        执行验证逻辑

        Args:
            target: 验证目标（如图片路径、截屏路径）
            context: 上下文信息（如 topic、image_type）

        Returns:
            验证结果对象（需有 passed 和 issues 属性）
        """
        pass

    @abstractmethod
    async def get_validation_target(
        self,
        agent_instance: Any,
        result: Any,
        context: dict
    ) -> Any:
        """
        从函数执行结果中提取验证目标

        Args:
            agent_instance: ImageAgent 实例
            result: 被装饰函数的返回值
            context: 上下文（kwargs）

        Returns:
            验证目标（传给 validate 方法）
        """
        pass

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """
        使类实例可作为装饰器使用

        装饰后的函数会在执行完成后自动进行验证，
        验证失败时按指数退避策略重试整个函数。
        """
        @wraps(func)
        async def wrapper(agent_instance, *args, **kwargs) -> T:
            last_error = None

            for attempt in range(self.max_retries + 1):
                # 使用 logfire span 追踪每次验证尝试
                with logfire.span(
                    f'validator:{self.validator_name}',
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    **{k: str(v)[:100] for k, v in kwargs.items() if isinstance(v, (str, int, float, bool))}
                ) as span:
                    try:
                        # 1. 执行被装饰的函数
                        result = await func(agent_instance, *args, **kwargs)

                        # 2. 获取验证目标
                        logger.debug(f"[{self.validator_name}] 准备验证...")
                        target = await self.get_validation_target(
                            agent_instance, result, kwargs
                        )

                        # 3. 执行验证
                        logger.debug(f"[{self.validator_name}] 开始分析...")
                        review = await self.validate(target, kwargs)

                        # 记录验证结果到 span
                        span.set_attribute('passed', review.passed)
                        if hasattr(review, 'issues'):
                            span.set_attribute('issues_count', len(review.issues))

                        if review.passed:
                            self._log_success(review)
                            logfire.info(
                                f'{self.validator_name} passed',
                                validator=self.validator_name,
                                attempt=attempt + 1
                            )
                            # 验证通过，删除临时截屏（如果存在）
                            if self._temp_screenshot and self._temp_screenshot.exists():
                                self._temp_screenshot.unlink()
                                logger.debug(f"[{self.validator_name}] 已删除临时截屏")
                            return result

                        # 4. 验证失败
                        last_error = ValidationError(review.issues)
                        span.set_attribute('failure_reason', review.summary if hasattr(review, 'summary') else str(review.issues))

                        # 更新 gen_ctx.validation_feedback 用于依赖注入
                        # 提示词生成 Agent 的动态 system_prompt 会读取该反馈
                        gen_ctx = kwargs.get('gen_ctx')
                        if gen_ctx is not None and hasattr(gen_ctx, 'validation_feedback'):
                            feedback = review.summary if hasattr(review, 'summary') else ', '.join(review.issues)
                            gen_ctx.validation_feedback = feedback
                            logger.info(f"[{self.validator_name}] 已更新验证反馈到 gen_ctx: {feedback[:100]}...")
                        
                        if attempt < self.max_retries:
                            delay = self.initial_delay * (2 ** attempt)
                            self._log_retry(review.summary, attempt, delay)
                            logfire.warn(
                                f'{self.validator_name} failed, retrying',
                                validator=self.validator_name,
                                attempt=attempt + 1,
                                retry_delay=delay
                            )
                            await asyncio.sleep(delay)
                        else:
                            logfire.error(
                                f'{self.validator_name} failed after all retries',
                                validator=self.validator_name,
                                total_attempts=attempt + 1
                            )
                            raise last_error

                    except ValidationError:
                        # ValidationError 已经在上面处理过了，直接抛出
                        raise
                    except Exception as e:
                        # 记录其他异常（如网络错误、Agent 调用失败等）
                        span.set_attribute('error', str(e)[:200])
                        logger.error(f"[{self.validator_name}] 验证异常: {type(e).__name__}")
                        logger.error(f"  {str(e)[:200]}")
                        raise

            raise last_error

        return wrapper

    def _log_success(self, review: Any) -> None:
        """记录验证成功"""
        logger.info(f"[{self.validator_name}] 验证通过")

    def _log_retry(self, reason: str, attempt: int, delay: float) -> None:
        """记录重试信息"""
        logger.warning(f"[{self.validator_name}] {reason}")
        logger.info(f"{delay:.0f}s 后重试 ({attempt + 1}/{self.max_retries})...")
