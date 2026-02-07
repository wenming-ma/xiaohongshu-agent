"""BaseAgent - 所有Agent的抽象基类"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import logfire
from pydantic import BaseModel


class RecoveryStrategy(Enum):
    """错误恢复策略"""

    RETRY = "retry"
    FALLBACK = "fallback"
    ABORT = "abort"


class ValidationResult(BaseModel):
    """验证结果"""

    passed: bool
    feedback: str = ""
    recovery: RecoveryStrategy = RecoveryStrategy.RETRY

    @classmethod
    def success(cls, feedback: str = "") -> "ValidationResult":
        return cls(passed=True, feedback=feedback)

    @classmethod
    def failure(
        cls, feedback: str, recovery: RecoveryStrategy = RecoveryStrategy.RETRY
    ) -> "ValidationResult":
        return cls(passed=False, feedback=feedback, recovery=recovery)


class BaseAgent(ABC):
    """所有Agent的抽象基类

    子类必须实现以下方法：
    - init_tools: 初始化工具
    - init_agent: 初始化内部pydantic_ai.Agent
    - forward: 主执行入口
    - step: 工作流子步骤
    - validate: 验证输出结果

    子类可定义类属性：
    - role: Agent角色
    - goal: Agent目标
    """

    role: str = ""
    goal: str = ""

    def __init__(self):
        self.init_tools()
        self.init_agent()

    def trace_span(self, operation: str):
        """创建追踪span"""
        return logfire.span(
            f"{self.__class__.__name__}.{operation}",
            agent_role=self.role,
            agent_goal=self.goal,
        )

    @abstractmethod
    def init_tools(self) -> None:
        """初始化工具（MCP服务器、验证器等）"""
        pass

    @abstractmethod
    def init_agent(self) -> None:
        """初始化pydantic_ai.Agent"""
        pass

    @abstractmethod
    def forward(self, *args, **kwargs) -> Any:
        """主执行入口"""
        pass

    @abstractmethod
    def step(self, *args, **kwargs) -> Any:
        """工作流子步骤"""
        pass

    @abstractmethod
    async def validate(self, output: Any) -> ValidationResult:
        """验证输出结果"""
        pass
