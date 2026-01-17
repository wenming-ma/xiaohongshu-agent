"""
图片生成验证模块

包含：
- 显式验证循环（替代装饰器堆叠）
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ...models.schemas import (
    XHSContent,
    ResearchResult,
    ImageTypeSpec,
    ImageGenContext,
    GeminiOperationResult,
)
from ...utils.logger import get_logger
from ...config.settings import TimeoutConfig
from .gemini_config_validator import GeminiConfigValidator
from .quality_validator import ImageQualityValidator

logger = get_logger(__name__)


# ============================================================================
# 显式验证循环
# ============================================================================

async def validate_image_generation(
    *,
    generate_core_fn,
    gemini_config_validator: GeminiConfigValidator,
    image_quality_validator: ImageQualityValidator,
    agent_instance: Any,
    gen_ctx: ImageGenContext,
    topic: str = "",
    image_type: str = "",
    content: Optional[XHSContent] = None,
    research: Optional[ResearchResult] = None,
    image_spec: Optional[ImageTypeSpec] = None,
    max_retries: int = 5,
) -> Path:
    """
    显式验证循环（替代装饰器堆叠）

    Args:
        generate_core_fn: 核心生成函数（async callable）
        gemini_config_validator: Gemini 配置验证器
        image_quality_validator: 图片质量验证器
        agent_instance: ImageAgent 实例（用于截屏等操作）
        gen_ctx: 生成上下文
        topic: 主题
        image_type: 图片类型
        content: 内容对象
        research: 研究结果
        image_spec: 图片规格
        max_retries: 最大重试次数

    Returns:
        Path: 生成的图片路径
    """
    image_path = None

    # 构建质量验证器所需的 context 字典
    quality_context = {
        "topic": topic,
        "image_type": image_type,
        "content": content,
        "research": research,
    }
    # 添加 image_type_info（如果 image_spec 存在）
    if image_spec is not None:
        quality_context["image_type_info"] = {
            "type": image_type,
            "desc": getattr(image_spec, "description", ""),
            "group_title": getattr(image_spec, "group_title", ""),
            "indices": getattr(image_spec, "key_info_indices", []),
        }

    for attempt in range(max_retries):
        try:
            # 生成图片
            image_path = await generate_core_fn()

            # 验证 Gemini 配置（通过截屏）
            logger.debug("验证 Gemini 配置...")
            # 截取 Gemini 页面
            screenshot_path = await gemini_config_validator.get_validation_target(
                agent_instance=agent_instance,
                result=image_path,
                context=quality_context,
            )
            config_review = await gemini_config_validator.validate(
                screenshot_path=screenshot_path,
                context=quality_context,
            )

            if not config_review.passed:
                logger.warning(
                    f"Gemini 配置验证失败 (attempt {attempt+1}/{max_retries}): {config_review.summary}"
                )
                # 等待一段时间后重试
                if attempt < max_retries - 1:
                    await asyncio.sleep(5.0)
                continue

            # 验证图片质量
            logger.debug("验证图片质量...")
            quality_review = await image_quality_validator.validate(
                image_path=image_path,
                context=quality_context,
            )

            if not quality_review.passed:
                logger.warning(
                    f"图片质量验证失败 (attempt {attempt+1}/{max_retries}): {quality_review.summary}"
                )
                # 将反馈注入到上下文，供下次生成使用
                gen_ctx.validation_feedback = quality_review.summary
                # 等待一段时间后重试
                if attempt < max_retries - 1:
                    await asyncio.sleep(5.0)
                continue

            # 验证通过
            logger.info(f"图片验证通过 (attempt {attempt+1})")
            return image_path

        except Exception as e:
            logger.warning(
                f"图片生成异常 (attempt {attempt+1}/{max_retries}): {type(e).__name__}: {e}"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(5.0)
            else:
                raise

    # 降级处理：验证失败多次后，返回最后生成的图片
    if image_path:
        logger.warning(
            f"验证失败 {max_retries} 次，降级返回最后生成的图片: {image_path}"
        )
        return image_path
    else:
        raise RuntimeError(f"图片生成失败：{max_retries} 次尝试后仍未成功")
