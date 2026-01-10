"""
内部验证器基类（循环内验证）
验证失败时返回反馈，由调用方继续探索（保持消息历史）

与 ExternalValidator 的区别：
- ExternalValidator：装饰器模式，失败后重试整个函数
- InternalValidator：返回反馈，失败后继续探索

使用场景：
- 研究任务：验证失败后需要继续探索，而非重新开始
- 需要保持消息历史的多轮交互任务
"""
from abc import ABC, abstractmethod
from typing import Any
import logfire
from ..utils.logger import get_logger

logger = get_logger(__name__)


class InternalValidationResult:
    """内部验证结果"""

    def __init__(self, passed: bool, feedback: str = "", score: float = 0.0):
        """
        初始化验证结果

        Args:
            passed: 是否通过验证
            feedback: 失败时的反馈信息（用于注入给 Agent 继续探索）
            score: 验证评分（0-100，可选）
        """
        self.passed = passed
        self.feedback = feedback
        self.score = score

    def __bool__(self) -> bool:
        """支持 if validation_result: 语法"""
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
                - passed: 是否通过
                - feedback: 失败时的反馈信息
                - score: 验证评分
        """
        pass

    def _log_result(self, validation_result: InternalValidationResult) -> None:
        """记录验证结果（同时输出到控制台和 Logfire）"""
        if validation_result.passed:
            logger.info(f"[{self.validator_name}] 验证通过")
            if validation_result.score > 0:
                logger.info(f"  - 评分: {validation_result.score:.1f}/100")
            # 记录到 Logfire
            logfire.info(
                f'{self.validator_name} passed',
                validator=self.validator_name,
                passed=True,
                score=validation_result.score
            )
        else:
            logger.warning(f"[{self.validator_name}] 验证未通过 (评分: {validation_result.score:.1f}/100)")
            if validation_result.feedback:
                # 提取关键反馈信息（显示前5行有意义的内容）
                lines = [line.strip() for line in validation_result.feedback.split('\n') if line.strip()]
                for line in lines[:5]:
                    # 移除 markdown 加粗符号，保留内容
                    clean_line = line.replace('**', '')
                    logger.warning(f"  {clean_line[:120]}")
            # 记录到 Logfire
            logfire.warn(
                f'{self.validator_name} failed',
                validator=self.validator_name,
                passed=False,
                score=validation_result.score,
                feedback_preview=validation_result.feedback[:500] if validation_result.feedback else None
            )
