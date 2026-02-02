"""BaseAgent - 所有Agent的抽象基类"""

from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel


class ValidationResult(BaseModel):
    """验证结果"""
    passed: bool
    feedback: str = ""

    @classmethod
    def success(cls, feedback: str = "") -> "ValidationResult":
        """创建成功结果"""
        return cls(passed=True, feedback=feedback)

    @classmethod
    def failure(cls, feedback: str) -> "ValidationResult":
        """创建失败结果"""
        return cls(passed=False, feedback=feedback)


class BaseAgent(ABC):
    """所有Agent的抽象基类

    子类必须实现以下方法：
    - init_tools: 初始化工具
    - init_agent: 初始化内部pydantic_ai.Agent
    - forward: 主执行入口
    - step: 工作流子步骤
    - validate: 验证输出结果
    """

    def __init__(self):
        """初始化Agent，自动调用init_tools和init_agent"""
        self.init_tools()
        self.init_agent()

    @abstractmethod
    def init_tools(self) -> None:
        """初始化工具

        子类必须实现此方法来初始化所需的工具，
        如MCP服务器、验证器、外部API客户端等。
        如果不需要工具，可以实现为空方法。
        """
        pass

    @abstractmethod
    def init_agent(self) -> None:
        """初始化内部pydantic_ai.Agent

        子类必须实现此方法来初始化内部的pydantic_ai.Agent实例，
        包括设置模型、系统提示、输出类型等。
        """
        pass

    @abstractmethod
    def forward(self, *args, **kwargs) -> Any:
        """主执行入口

        子类必须实现此方法作为Agent的主要执行逻辑。
        这是外部调用Agent的主要接口。

        Returns:
            执行结果，类型由子类定义
        """
        pass

    @abstractmethod
    def step(self, *args, **kwargs) -> Any:
        """工作流子步骤

        子类必须实现此方法来定义工作流的子步骤。
        通常包括：准备 -> 执行 -> 后处理 等阶段。

        Returns:
            步骤执行结果，类型由子类定义
        """
        pass

    @abstractmethod
    async def validate(self, output: Any) -> ValidationResult:
        """验证输出结果

        子类必须实现此方法来验证Agent的输出是否符合预期。

        Args:
            output: 需要验证的输出结果

        Returns:
            ValidationResult: 验证结果，包含 passed 和 feedback
        """
        pass
