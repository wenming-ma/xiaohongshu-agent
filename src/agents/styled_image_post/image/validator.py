"""图片质量验证器"""
from pathlib import Path
from typing import Any
from pydantic_ai import Agent, BinaryContent
from ....core.base_validator import ExternalValidator
from ..schemas import ImageQualityReview
from ...shared.utils.image_compression import compress_image_for_review
from ....utils.providers import get_google_model
from ....utils.logger import get_logger
from ....config.settings import APIConfig
from .prompts import image_quality_review_system_prompt, image_quality_review_user_prompt

logger = get_logger(__name__)


class ImageQualityValidator(ExternalValidator):
    """图片质量验证器 - 可直接作为装饰器使用"""

    @property
    def validator_name(self) -> str:
        return "ImageQuality"

    @property
    def fail_open(self) -> bool:
        return True

    @property
    def agent(self) -> Agent:
        """延迟初始化 Agent"""
        if self._agent is None:
            from ....config.settings import RetryConfig
            self._agent = Agent(
                model=get_google_model(APIConfig.GOOGLE_VISION_MODEL),
                output_type=ImageQualityReview,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,
                system_prompt=(image_quality_review_system_prompt(),),
            )
        return self._agent

    async def get_validation_target(
        self,
        agent_instance: Any,
        result: Any,
        context: dict
    ) -> Path:
        """图片路径作为验证目标"""
        return result

    async def validate(self, image_path: Path, context: dict) -> ImageQualityReview:
        """验证图片质量"""
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

        image_data = await compress_image_for_review(image_path, max_size_mb=5.0)
        topic = context.get("topic", "")
        image_type = context.get("image_type", "")
        content = context.get("content")
        content_title = getattr(content, "title", "") if content is not None else ""
        expected_content = self._build_expected_content(context)
        image_prompt = context.get("image_prompt", "（未提供）")

        user_prompt = image_quality_review_user_prompt(
            topic=topic,
            image_type=image_type,
            content_title=content_title,
            expected_content=expected_content,
            image_prompt=image_prompt,
        )

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
        """记录验证成功"""
        logger.info(
            f"[{self.validator_name}] 质量通过 "
            f"(清晰度: {review.text_clarity_score:.0f}, 风格: {review.style_score:.0f})"
        )
