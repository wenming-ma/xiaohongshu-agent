"""
Google Gemini Model 工厂
提供带 HTTP 重试机制的共享 Google Model

使用 pydantic-ai 官方的 GoogleModel：
- 支持视觉模型：gemini-2.5-flash, gemini-3-flash-preview
- 需要设置 GOOGLE_API_KEY 环境变量
"""
import os
from pydantic_ai.models.google import GoogleModel

from ..config.settings import APIConfig


# 全局共享的 Model 实例（避免重复创建）
_shared_model: GoogleModel | None = None


def get_google_model(
    model_name: str = None
) -> GoogleModel:
    """
    获取配置好的 Google Gemini Model

    Args:
        model_name: 模型名称，默认使用配置中的 GOOGLE_MODEL

    Returns:
        GoogleModel 实例
    """
    global _shared_model
    model_name = model_name or APIConfig.GOOGLE_MODEL

    # 检查环境变量
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY 环境变量未设置")

    # 每次返回新实例（因为模型名称可能不同）
    # GoogleModel 内部会自动处理 API key
    return GoogleModel(model_name, provider='google-gla')
