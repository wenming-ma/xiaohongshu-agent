"""ToolRegistry - 工具注册和发现"""

from typing import Type
from pydantic_ai import Tool

from .base_tool import BasePlatformTool


class ToolRegistry:
    """工具注册表，管理所有平台工具的注册和发现"""

    _tools: dict[str, Type[BasePlatformTool]] = {}
    _instances: dict[str, BasePlatformTool] = {}

    @classmethod
    def register(cls, tool_class: Type[BasePlatformTool]) -> Type[BasePlatformTool]:
        """装饰器：注册工具类"""
        cls._tools[tool_class.name] = tool_class
        return tool_class

    @classmethod
    def get_tool(cls, name: str) -> BasePlatformTool:
        """获取或创建工具实例"""
        if name not in cls._instances:
            if name not in cls._tools:
                raise ValueError(f"Unknown tool: {name}")
            cls._instances[name] = cls._tools[name]()
        return cls._instances[name]

    @classmethod
    def get_all_tools(cls) -> list[BasePlatformTool]:
        """获取所有已注册工具的实例"""
        return [cls.get_tool(name) for name in cls._tools]

    @classmethod
    def get_tools_by_platform(cls, platform: str) -> list[BasePlatformTool]:
        """获取指定平台的所有工具"""
        return [
            cls.get_tool(name)
            for name, tool_cls in cls._tools.items()
            if tool_cls.platform == platform
        ]

    @classmethod
    def get_tool_descriptions(cls) -> str:
        """生成工具描述文本供 MasterAgent 使用"""
        descriptions = []
        for name, tool_cls in cls._tools.items():
            desc = tool_cls.description[:150]
            if len(tool_cls.description) > 150:
                desc += "..."
            descriptions.append(
                f"- **{name}** ({tool_cls.platform}/{tool_cls.content_type}): {desc}"
            )
        return "\n".join(descriptions)

    @classmethod
    def get_pydantic_tools(cls) -> list[Tool]:
        """获取所有工具的 pydantic_ai Tool 对象"""
        return [tool.get_pydantic_tool() for tool in cls.get_all_tools()]

    @classmethod
    def clear(cls) -> None:
        """清空注册表（用于测试）"""
        cls._tools.clear()
        cls._instances.clear()
