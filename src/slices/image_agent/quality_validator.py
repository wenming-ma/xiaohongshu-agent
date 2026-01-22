"""
图片质量验证器
检查生成的图片是否符合小红书质量标准

验证项目：
- 文字清晰度
- 风格匹配度
- 图片比例
- 文字语言
- 内容相关性（与当前分组/图片类型要求一致）

使用方式：
    @ImageQualityValidator(max_retries=2)
    async def _generate_via_gemini(self, prompt, output_dir, image_type, topic=""):
        ...
"""
from pathlib import Path
from typing import Any
from pydantic_ai import Agent, BinaryContent
from ...validators.external_base import ExternalValidator
from ...models.schemas import ImageQualityReview
from ...utils.image_compression import compress_image_for_review
from ...utils.anthropic_provider import get_anthropic_model
from ...utils.logger import get_logger
from ...config.settings import APIConfig
from .prompts import image_quality_review_system_prompt, image_quality_review_user_prompt

logger = get_logger(__name__)


class ImageQualityValidator(ExternalValidator):
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
    def fail_open(self) -> bool:
        # 图片质量审核失败通常属于“内容不理想/跑题”等门禁问题；
        # 为避免整条工作流因为审图不通过而无法发布，这里选择降级放行：
        # 仍会记录 issues/summary，但返回最后一次生成的图片供后续发布使用。
        return True

    @property
    def agent(self) -> Agent:
        """延迟初始化 Agent（首次使用时创建）"""
        if self._agent is None:
            from ...config.settings import RetryConfig
            self._agent = Agent(
                model=get_anthropic_model(APIConfig.CLAUDE_IMAGE_MODEL),
                output_type=ImageQualityReview,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,  # Agent 内部重试
                system_prompt=(image_quality_review_system_prompt(),),
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

        # 压缩图片文件（API 限制 5MB）
        image_data = await compress_image_for_review(image_path, max_size_mb=5.0)

        # 从上下文获取 topic（用于风格验证）
        topic = context.get("topic", "")

        image_type = context.get("image_type", "")
        content = context.get("content")
        content_title = getattr(content, "title", "") if content is not None else ""
        expected_content = self._build_expected_content(context)

        # 获取用户提示词
        user_prompt = image_quality_review_user_prompt(
            topic=topic,
            image_type=image_type,
            content_title=content_title,
            expected_content=expected_content,
        )

        # 使用 Agent 分析图片（使用压缩后的 JPEG）
        result = await self.agent.run(
            [
                user_prompt,
                BinaryContent(data=image_data, media_type='image/jpeg')
            ]
        )

        return result.output

    @staticmethod
    def _build_expected_content(context: dict) -> str:
        image_type_info = context.get("image_type_info") or {}
        image_desc = image_type_info.get("desc", "") if isinstance(image_type_info, dict) else ""
        group_title = image_type_info.get("group_title", "") if isinstance(image_type_info, dict) else ""

        content = context.get("content")
        research = context.get("research")

        parts: list[str] = []
        if image_desc:
            parts.append(f"图片目标：{image_desc}")

        if not isinstance(image_type_info, dict) or image_type_info.get("type") == "cover":
            if content is not None:
                body = getattr(content, "body", "") or ""
                if body:
                    parts.append(f"正文要点（节选）：{body[:200]}")
            return "\n".join(parts) if parts else "（未提供）"

        if group_title:
            parts.append(f"主题板块：{group_title}")

        indices = image_type_info.get("indices", [])
        if not isinstance(indices, list) or not indices:
            return "\n".join(parts) if parts else "（未提供）"

        key_infos = getattr(research, "key_infos", None) if research is not None else None
        if not isinstance(key_infos, list) or not key_infos:
            return "\n".join(parts) if parts else "（未提供）"

        selected_infos: list[dict] = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(key_infos):
                info = key_infos[idx]
                if isinstance(info, dict):
                    selected_infos.append(info)

        if selected_infos:
            infos_text = "\n".join(
                f"{i+1}. {info.get('name', '未知')}: {info.get('description', info.get('detail', ''))}"
                for i, info in enumerate(selected_infos)
            )
            parts.append(f"本图必须覆盖的关键信息（共 {len(selected_infos)} 条）：\n{infos_text}")

        return "\n".join(parts) if parts else "（未提供）"

    def _log_success(self, review: ImageQualityReview) -> None:
        """记录验证成功（覆盖基类方法以显示评分）"""
        logger.info(
            f"[{self.validator_name}] 质量通过 "
            f"(清晰度: {review.text_clarity_score:.0f}, 风格: {review.style_score:.0f})"
        )
