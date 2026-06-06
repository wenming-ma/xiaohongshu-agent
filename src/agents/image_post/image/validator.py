"""图片质量验证器"""
from pathlib import Path
from typing import Any
from ....core.base_validator import ExternalValidator
from ..schemas import ImageQualityReview
from ...shared.utils.image_compression import compress_image_for_review
from ....utils.providers import VertexAIVisionClient
from ....utils.logger import get_logger
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
    def vision_client(self) -> VertexAIVisionClient:
        """延迟初始化视觉客户端"""
        if self._agent is None:
            self._agent = VertexAIVisionClient()
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

        topic = context.get("topic", "")
        image_type = context.get("image_type", "")
        content = context.get("content")
        content_title = getattr(content, "title", "") if content is not None else ""
        expected_content = self._build_expected_content(context)
        image_prompt = context.get("image_prompt", "（未提供）")
        reference_images = self._reference_image_paths(context)

        user_prompt = image_quality_review_user_prompt(
            topic=topic,
            image_type=image_type,
            content_title=content_title,
            expected_content=expected_content,
            image_prompt=image_prompt,
        )

        if reference_images:
            return await self.vision_client.analyze_images_structured(
                images=[("generated_image", image_path), *reference_images],
                prompt=user_prompt,
                system_prompt=image_quality_review_system_prompt(),
                response_model=ImageQualityReview,
            )

        image_data = await compress_image_for_review(image_path, max_size_mb=5.0)
        return await self.vision_client.analyze_image_bytes_structured(
            image_bytes=image_data,
            media_type="image/jpeg",
            prompt=user_prompt,
            system_prompt=image_quality_review_system_prompt(),
            response_model=ImageQualityReview,
        )

    @staticmethod
    def _reference_image_paths(context: dict) -> list[tuple[str, Path]]:
        references = context.get("reference_images") or []
        paths: list[tuple[str, Path]] = []
        for index, ref in enumerate(references):
            label = f"reference_{index + 1}"
            path_value: object | None = None
            if hasattr(ref, "label"):
                label = str(getattr(ref, "label") or label)
            if hasattr(ref, "path"):
                path_value = getattr(ref, "path")
            elif isinstance(ref, dict):
                label = str(ref.get("label") or label)
                path_value = ref.get("path")
            elif isinstance(ref, (str, Path)):
                path_value = ref
            if path_value is None:
                continue
            path = Path(str(path_value))
            if path.exists():
                paths.append((label, path))
        return paths

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
        style_constraints = ImageQualityValidator._string_list(context.get("style_constraints"))
        hard_constraints = ImageQualityValidator._string_list(context.get("hard_constraints"))
        negative_constraints = ImageQualityValidator._string_list(context.get("negative_constraints"))
        if style_constraints:
            parts.append("用户风格约束：\n" + "\n".join(f"- {item}" for item in style_constraints))
        if hard_constraints:
            parts.append("硬性视觉约束：\n" + "\n".join(f"- {item}" for item in hard_constraints))
        if negative_constraints:
            parts.append("硬性禁用项：\n" + "\n".join(f"- {item}" for item in negative_constraints))

        image_task_text = ImageQualityValidator._image_task_expected_content(
            context.get("image_task")
        )
        if image_task_text:
            parts.append(image_task_text)

        reference_images = context.get("reference_images") or []
        reference_intent = str(context.get("reference_intent") or "none")
        if reference_images:
            parts.append(ImageQualityValidator._reference_expectation(reference_intent))

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

        research_items = getattr(research, "items", None) if research is not None else None
        if not isinstance(research_items, list) or not research_items:
            return "\n".join(parts) if parts else "（未提供）"

        selected_infos: list[tuple[str, str]] = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(research_items):
                item = research_items[idx]
                if hasattr(item, "title"):
                    selected_infos.append((item.title, item.content))
                elif isinstance(item, dict):
                    selected_infos.append(
                        (
                            item.get("title", item.get("name", "未知")),
                            item.get("content", item.get("description", item.get("detail", ""))),
                        )
                    )

        if selected_infos:
            infos_text = "\n".join(
                f"{i+1}. {title or '未知'}: {text or ''}"
                for i, (title, text) in enumerate(selected_infos)
            )
            parts.append(
                f"本图参考信息（共 {len(selected_infos)} 条，仅用于判断大方向是否相关，不要求逐条写出或全部出现）：\n"
                f"{infos_text}"
            )

        return "\n".join(parts) if parts else "（未提供）"

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return result

    @staticmethod
    def _image_task_expected_content(image_task: Any) -> str:
        if not image_task:
            return ""
        task_data = ImageQualityValidator._image_task_data(image_task)
        if not task_data:
            return ""

        lines = ["图片任务规划："]
        for field_name in ("image_type", "group_title", "generation_mode", "description"):
            value = str(task_data.get(field_name) or "").strip()
            if value:
                lines.append(f"{field_name}: {value}")

        references = task_data.get("reference_images") or []
        if references:
            lines.append("reference_images:")
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                label = str(reference.get("label") or "reference").strip()
                role = str(reference.get("role") or "").strip()
                notes = str(reference.get("notes") or "").strip()
                line = f"- {label}"
                if role:
                    line += f" | role={role}"
                if notes:
                    line += f" | notes={notes}"
                lines.append(line)

        for field_name in ("hard_constraints", "qa_rules"):
            values = ImageQualityValidator._string_list(task_data.get(field_name))
            if not values:
                continue
            lines.append(f"{field_name}:")
            lines.extend(f"- {item}" for item in values)

        return "\n".join(lines)

    @staticmethod
    def _image_task_data(image_task: Any) -> dict[str, Any]:
        if isinstance(image_task, dict):
            return dict(image_task)
        model_dump = getattr(image_task, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        return {}

    @staticmethod
    def _reference_expectation(reference_intent: str) -> str:
        if reference_intent in {"object_transfer", "subject_reference"}:
            return (
                "用户提供了参考图片；生成图必须包含参考图片中的核心衣物、服装、首饰或物品，"
                "并尽量保持其颜色、轮廓、材质和可识别细节，不能只做风格迁移。"
            )
        if reference_intent == "style_reference":
            return (
                "用户提供了参考图片；参考图只用于风格、色调、光线、构图、材质质感或氛围，"
                "不得要求保留参考图中的具体物体，也不要把参考图当作截图或拼贴插入。"
            )
        if reference_intent == "composition_reference":
            return (
                "用户提供了参考图片；参考图只用于构图、版式、镜头角度、画面比例或空间布局，"
                "不得要求保留参考图中的具体物体。"
            )
        if reference_intent == "scene_reference":
            return (
                "用户提供了参考图片；参考图只用于场景类型、环境氛围、空间关系或地点线索，"
                "不得要求保留参考图中的具体物体。"
            )
        if reference_intent == "material_color_reference":
            return (
                "用户提供了参考图片；参考图只用于材质纹理、面料质感、色彩搭配或表面细节，"
                "不得要求保留参考图中的具体物体。"
            )
        return (
            "用户提供了参考图片；参考用途未明确时，优先作为风格、氛围或构图参考，"
            "不要默认要求迁移参考图中的具体物体。"
        )

    def _log_success(self, review: ImageQualityReview) -> None:
        """记录验证成功"""
        logger.info(
            f"[{self.validator_name}] 质量通过 "
            f"(清晰度: {review.text_clarity_score:.0f}, 风格: {review.style_score:.0f})"
        )
