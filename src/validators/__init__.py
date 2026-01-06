"""
专用验证器模块
每个验证器负责特定的验证任务，便于扩展和复用

外部验证器（装饰器模式，失败后重试整个函数）：
    @GeminiConfigValidator(max_retries=3)
    @ImageQualityValidator(max_retries=2)
    async def _generate_via_gemini(self, ...):
        ...

内部验证器（循环内验证，失败后继续探索）：
    validator = ResearchDepthValidator(min_posts=3)
    result = await validator.validate(research_result, context)
    if not result.passed:
        # 使用 result.feedback 继续探索
"""
# 外部验证器（装饰器模式）
from .external_base import ExternalValidator, ValidationError
from .gemini_config_validator import GeminiConfigValidator
from .image_quality_validator import ImageQualityValidator

# 内部验证器（循环内验证）
from .internal_base import InternalValidator, InternalValidationResult
from .research_depth_validator import ResearchDepthValidator
from .research_review_validator import ResearchReviewValidator

__all__ = [
    # 外部验证器（装饰器模式）
    "ExternalValidator",
    "ValidationError",
    "GeminiConfigValidator",
    "ImageQualityValidator",
    # 内部验证器（循环内验证）
    "InternalValidator",
    "InternalValidationResult",
    "ResearchDepthValidator",
    "ResearchReviewValidator",
]
