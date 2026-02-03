"""
验证器基类

包含：
- InternalValidator: 内部验证器（循环内验证，返回反馈继续探索）
- ExternalValidator: 外部验证器（装饰器模式，失败重试整个函数）
"""
from abc import ABC, abstractmethod
from functools import wraps
import asyncio
from typing import Any, Callable, TypeVar
import logfire
from ..utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


# ============================================================================
# 内部验证器（循环内验证）
# ============================================================================


class InternalValidationResult:
    """内部验证结果"""

    def __init__(self, passed: bool, feedback: str = "", score: float = 0.0):
        self.passed = passed
        self.feedback = feedback
        self.score = score

    def __bool__(self) -> bool:
        return self.passed


class InternalValidator(ABC):
    """
    内部验证器基类

    特点：
    - 在函数内部循环中调用
    - 验证失败时返回反馈，而非重试整个函数
    - 保持消息历史，支持继续探索

    子类需实现：
    - validator_name: 验证器名称（用于日志）
    - validate(): 验证逻辑
    """

    @property
    @abstractmethod
    def validator_name(self) -> str:
        """验证器名称（用于日志显示）"""
        pass

    @abstractmethod
    async def validate(
        self,
        result: Any,
        context: dict
    ) -> InternalValidationResult:
        """
        验证结果

        Args:
            result: 需要验证的结果对象
            context: 上下文信息（如 topic、target_audience 等）

        Returns:
            InternalValidationResult: 验证结果
        """
        pass

    def _log_result(self, validation_result: InternalValidationResult) -> None:
        """记录验证结果"""
        if validation_result.passed:
            logger.info(f"[{self.validator_name}] 验证通过")
            if validation_result.score > 0:
                logger.info(f"  - 评分: {validation_result.score:.1f}/100")
            logfire.info(
                f'{self.validator_name} passed',
                validator=self.validator_name,
                passed=True,
                score=validation_result.score
            )
        else:
            logger.warning(f"[{self.validator_name}] 验证未通过 (评分: {validation_result.score:.1f}/100)")
            if validation_result.feedback:
                lines = [line.strip() for line in validation_result.feedback.split('\n') if line.strip()]
                for line in lines[:5]:
                    clean_line = line.replace('**', '')
                    logger.warning(f"  {clean_line[:120]}")
            logfire.warn(
                f'{self.validator_name} failed',
                validator=self.validator_name,
                passed=False,
                score=validation_result.score,
                feedback_preview=validation_result.feedback[:500] if validation_result.feedback else None
            )


# ============================================================================
# 外部验证器（装饰器模式）
# ============================================================================


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
        @ImageQualityValidator(max_retries=2)
        async def _generate_via_gemini(self, prompt, output_dir, image_type):
            ...
    """

    def __init__(self, max_retries: int = 5, initial_delay: float = 5.0):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self._agent = None
        self._temp_screenshot = None

    @property
    @abstractmethod
    def validator_name(self) -> str:
        """验证器名称（用于日志显示）"""
        pass

    @property
    def fail_open(self) -> bool:
        """验证失败是否允许降级放行"""
        return False

    @abstractmethod
    async def validate(self, target: Any, context: dict) -> Any:
        """执行验证逻辑"""
        pass

    @abstractmethod
    async def get_validation_target(
        self,
        agent_instance: Any,
        result: Any,
        context: dict
    ) -> Any:
        """从函数执行结果中提取验证目标"""
        pass

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """使类实例可作为装饰器使用"""
        @wraps(func)
        async def wrapper(agent_instance, *args, **kwargs) -> T:
            last_error = None

            for attempt in range(self.max_retries + 1):
                with logfire.span(
                    f'validator:{self.validator_name}',
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    **{k: str(v)[:100] for k, v in kwargs.items() if isinstance(v, (str, int, float, bool))}
                ) as span:
                    try:
                        result = await func(agent_instance, *args, **kwargs)

                        logger.debug(f"[{self.validator_name}] 准备验证...")
                        target = await self.get_validation_target(
                            agent_instance, result, kwargs
                        )

                        logger.debug(f"[{self.validator_name}] 开始分析...")
                        review = await self.validate(target, kwargs)

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
                            gen_ctx = kwargs.get('gen_ctx')
                            if gen_ctx is not None and hasattr(gen_ctx, 'validation_feedback'):
                                gen_ctx.validation_feedback = None

                            if self._temp_screenshot and self._temp_screenshot.exists():
                                self._temp_screenshot.unlink()
                                logger.debug(f"[{self.validator_name}] 已删除临时截屏")
                            return result

                        last_error = ValidationError(review.issues)
                        span.set_attribute('failure_reason', review.summary if hasattr(review, 'summary') else str(review.issues))

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
                            if self.fail_open:
                                logger.warning(
                                    "[%s] 验证未通过但启用 fail-open，将使用最后一次结果继续: %s",
                                    self.validator_name,
                                    (review.summary if hasattr(review, "summary") else str(review.issues))[:200],
                                )
                                logfire.warn(
                                    f'{self.validator_name} retries exhausted (fail-open)',
                                    validator=self.validator_name,
                                    total_attempts=attempt + 1,
                                )
                                return result
                            logfire.error(
                                f'{self.validator_name} failed after all retries',
                                validator=self.validator_name,
                                total_attempts=attempt + 1
                            )
                            raise last_error

                    except ValidationError:
                        raise
                    except Exception as e:
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
