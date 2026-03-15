"""BasePipeline - 所有平台流水线的抽象基类"""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar
from pydantic import BaseModel
from pydantic_ai import Tool

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class BasePipeline(ABC, Generic[InputT, OutputT]):
    """平台流水线抽象基类

    每个流水线封装一个完整的工作流，可以被 MasterAgent 调用。
    遵循 HuggingFace 风格：保持简单、保持隔离。
    """

    name: str
    description: str
    platform: str
    content_type: str
    input_schema: type[InputT]
    output_schema: type[OutputT]

    @abstractmethod
    async def execute(self, input_data: InputT) -> OutputT:
        """执行工作流

        Args:
            input_data: 符合 input_schema 的输入数据

        Returns:
            符合 output_schema 的输出数据
        """
        pass

    def get_pydantic_tool(self) -> Tool:
        """返回 pydantic_ai Tool 供 MasterAgent 使用"""
        async def tool_func(**kwargs: Any) -> dict[str, Any]:
            input_data = self.input_schema(**kwargs)
            result = await self.execute(input_data)
            return result.model_dump()

        tool_func.__name__ = self.name
        tool_func.__doc__ = self.description

        return Tool(tool_func, takes_ctx=False)

    @classmethod
    def get_pipeline_info(cls) -> dict[str, Any]:
        """返回流水线元信息"""
        return {
            "name": cls.name,
            "description": cls.description,
            "platform": cls.platform,
            "content_type": cls.content_type,
            "input_schema": cls.input_schema.model_json_schema(),
            "output_schema": cls.output_schema.model_json_schema(),
        }
