"""
图片质量验证器
检查生成的图片是否符合小红书质量标准

验证项目：
- 文字清晰度
- 风格匹配度
- 图片比例
- 文字语言

使用方式：
    @ImageQualityValidator(max_retries=2)
    async def _generate_via_gemini(self, prompt, output_dir, image_type, topic=""):
        ...
"""
from pathlib import Path
from typing import Any
from pydantic_ai import Agent, BinaryContent
from .base import BaseValidator
from ..models.schemas import ImageQualityReview
from prompts import get_system_prompt, get_user_prompt


class ImageQualityValidator(BaseValidator):
    """
    图片质量验证器 - 可直接作为装饰器使用

    验证生成的图片质量：
    1. 文字是否清晰可读
    2. 风格是否符合小红书审美
    3. 比例是否为 3:4 竖版
    4. 文字是否为中文

    验证失败时自动重试整个被装饰的函数。
    """

    @property
    def validator_name(self) -> str:
        return "ImageQuality"

    @property
    def agent(self) -> Agent:
        """延迟初始化 Agent（首次使用时创建）"""
        if self._agent is None:
            from ..utils.anthropic_provider import get_anthropic_model
            self._agent = Agent(
                model=get_anthropic_model(),
                output_type=ImageQualityReview,
                instrument=True,
                system_prompt=(get_system_prompt("image_quality_review"),),
            )
        return self._agent

    async def get_validation_target(
        self,
        agent_instance: Any,
        result: Any,
        context: dict
    ) -> Path:
        """
        图片路径作为验证目标

        Args:
            agent_instance: ImageAgent 实例（未使用）
            result: 被装饰函数的返回值（即图片路径）
            context: 上下文信息

        Returns:
            图片路径
        """
        # _generate_via_gemini 返回的就是图片路径
        return result

    async def validate(self, image_path: Path, context: dict) -> ImageQualityReview:
        """
        验证图片质量

        通过 AI 分析图片，检查：
        1. 文字清晰度评分 (0-100)
        2. 风格匹配度评分 (0-100)
        3. 图片比例是否为 3:4 竖版
        4. 文字是否为中文

        Args:
            image_path: 图片路径
            context: 上下文（包含 topic 用于风格匹配验证）

        Returns:
            ImageQualityReview: 验证结果
        """
        # 检查图片文件
        if not image_path.exists():
            return ImageQualityReview(
                passed=False,
                text_clarity_score=0.0,
                style_score=0.0,
                aspect_ratio_correct=False,
                text_is_chinese=False,
                issues=["图片文件不存在"],
                summary="无法验证：图片文件不存在"
            )

        # 读取图片文件
        image_data = image_path.read_bytes()

        # 从上下文获取 topic（用于风格验证）
        topic = context.get("topic", "")

        # 获取用户提示词
        user_prompt = get_user_prompt("image_quality_review", topic=topic)

        # 使用 Agent 分析图片
        result = await self.agent.run(
            [
                user_prompt,
                BinaryContent(data=image_data, media_type='image/png')
            ]
        )

        return result.output

    def _log_success(self, review: ImageQualityReview) -> None:
        """记录验证成功（覆盖基类方法以显示评分）"""
        print(
            f"         ✅ [{self.validator_name}] 质量通过 "
            f"(清晰度: {review.text_clarity_score:.0f}, 风格: {review.style_score:.0f})"
        )
