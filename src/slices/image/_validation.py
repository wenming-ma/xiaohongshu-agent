"""
图片生成验证模块

包含：
- 显式验证循环（替代装饰器堆叠）
"""
import asyncio
import time
from pathlib import Path

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
    gen_ctx: ImageGenContext,
    max_retries: int = 5,
) -> Path:
    """
    显式验证循环（替代装饰器堆叠）

    Args:
        generate_core_fn: 核心生成函数（async callable）
        gemini_config_validator: Gemini 配置验证器
        image_quality_validator: 图片质量验证器
        gen_ctx: 生成上下文
        max_retries: 最大重试次数

    Returns:
        Path: 生成的图片路径
    """
    image_path = None

    for attempt in range(max_retries):
        try:
            # 生成图片
            image_path = await generate_core_fn()

            # 验证 Gemini 配置
            logger.debug("验证 Gemini 配置...")
            config_review = await gemini_config_validator.validate(
                image_path=image_path,
                gen_ctx=gen_ctx,
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
                gen_ctx=gen_ctx,
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
