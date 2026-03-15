"""PipelineRegistry - 流水线注册和发现"""

from typing import Type
from pydantic_ai import Tool

from .base_pipeline import BasePipeline


class PipelineRegistry:
    """流水线注册表，管理所有平台流水线的注册和发现"""

    _pipelines: dict[str, Type[BasePipeline]] = {}
    _instances: dict[str, BasePipeline] = {}

    @classmethod
    def register(cls, pipeline_class: Type[BasePipeline]) -> Type[BasePipeline]:
        """装饰器：注册流水线类"""
        cls._pipelines[pipeline_class.name] = pipeline_class
        return pipeline_class

    @classmethod
    def get_pipeline(cls, name: str) -> BasePipeline:
        """获取或创建流水线实例"""
        if name not in cls._instances:
            if name not in cls._pipelines:
                raise ValueError(f"Unknown pipeline: {name}")
            cls._instances[name] = cls._pipelines[name]()
        return cls._instances[name]

    @classmethod
    def get_all_pipelines(cls) -> list[BasePipeline]:
        """获取所有已注册流水线的实例"""
        return [cls.get_pipeline(name) for name in cls._pipelines]

    @classmethod
    def get_pipelines_by_platform(cls, platform: str) -> list[BasePipeline]:
        """获取指定平台的所有流水线"""
        return [
            cls.get_pipeline(name)
            for name, pipeline_cls in cls._pipelines.items()
            if pipeline_cls.platform == platform
        ]

    @classmethod
    def get_pipeline_descriptions(cls) -> str:
        """生成流水线描述文本供 MasterAgent 使用"""
        descriptions = []
        for name, pipeline_cls in cls._pipelines.items():
            desc = pipeline_cls.description[:150]
            if len(pipeline_cls.description) > 150:
                desc += "..."
            descriptions.append(
                f"- **{name}** ({pipeline_cls.platform}/{pipeline_cls.content_type}): {desc}"
            )
        return "\n".join(descriptions)

    @classmethod
    def get_pydantic_tools(cls) -> list[Tool]:
        """获取所有流水线的 pydantic_ai Tool 对象"""
        return [pipeline.get_pydantic_tool() for pipeline in cls.get_all_pipelines()]

    @classmethod
    def clear(cls) -> None:
        """清空注册表（用于测试）"""
        cls._pipelines.clear()
        cls._instances.clear()
