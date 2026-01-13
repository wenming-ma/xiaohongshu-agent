"""
Mistral AI Provider
提供带 HTTP 重试机制的 Mistral 视觉模型

使用 pydantic-ai 的原生 Mistral 支持：
- MistralModel 和 MistralProvider
- 支持视觉的模型: pixtral-12b-latest, devstral-small-latest, ministral-3b-latest
- 支持图片格式: JPEG, PNG, GIF, WebP
- 原生支持结构化输出（tool_calls）
"""
import os
from pydantic_ai.models.mistral import MistralModel
from pydantic_ai.providers.mistral import MistralProvider


# 全局共享的 Provider 实例（避免重复创建）
_shared_provider: MistralProvider | None = None

# 默认视觉模型（支持图片输入且免费/低价的模型）
# 可选: pixtral-12b-latest, devstral-small-latest, ministral-3b-latest
MISTRAL_VISION_MODEL = "pixtral-12b-latest"


def get_mistral_model(
    model_name: str = None
) -> MistralModel:
    """
    获取配置好的 Mistral Model（使用原生 Mistral API）

    Mistral 视觉 API 支持：
    - 图片 URL 输入
    - Base64 编码图片输入
    - 支持格式: JPEG, PNG, GIF, WebP

    支持视觉的模型：
    - pixtral-12b-latest (推荐，专门的视觉模型)
    - devstral-small-latest (代码+视觉)
    - ministral-3b-latest (轻量级)
    - pixtral-large-latest (最强，但较贵)

    Args:
        model_name: 模型名称，默认使用 pixtral-12b-latest

    Returns:
        MistralModel 实例
    """
    global _shared_provider
    model_name = model_name or MISTRAL_VISION_MODEL

    if _shared_provider is None:
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY 环境变量未设置")

        # 创建原生 Mistral Provider
        _shared_provider = MistralProvider(api_key=api_key)

    # 创建 Model（使用共享 Provider）
    return MistralModel(model_name, provider=_shared_provider)
