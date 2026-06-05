from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from .skills import SkillSpec


class StylePromptRef(BaseModel):
    source: str
    title: str = ""
    excerpt: str = ""
    tags: list[str] = Field(default_factory=list)


class ReferenceImageRef(BaseModel):
    label: str
    path: str
    mime_type: str = ""


class StyleContext(BaseModel):
    user_constraints: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    prompt_refs: list[StylePromptRef] = Field(default_factory=list)
    reference_images: list[ReferenceImageRef] = Field(default_factory=list)
    reference_intent: str = "none"
    hard_constraints: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        request: Any,
        *,
        matched_skills: Sequence[SkillSpec] = (),
    ) -> "StyleContext":
        user_constraints = _dedupe(getattr(request, "style_constraints", []) or [])
        reference_images = _build_reference_images(getattr(request, "reference_images", []) or [])
        reference_intent = _derive_reference_intent(request, user_constraints, reference_images)
        hard_constraints = _derive_hard_constraints(
            request,
            user_constraints,
            reference_images=reference_images,
            reference_intent=reference_intent,
        )
        negative_constraints = _derive_negative_constraints(user_constraints)
        prompt_refs: list[StylePromptRef] = []
        for skill in matched_skills:
            prompt_refs.extend(_load_skill_prompt_refs(skill))

        return cls(
            user_constraints=user_constraints,
            matched_skills=[skill.name for skill in matched_skills],
            prompt_refs=prompt_refs,
            reference_images=reference_images,
            reference_intent=reference_intent,
            hard_constraints=hard_constraints,
            negative_constraints=negative_constraints,
            trace={
                "source": "conversation_request_and_project_skills",
                "skill_count": len(matched_skills),
                "prompt_ref_count": len(prompt_refs),
                "reference_image_count": len(reference_images),
                "reference_intent": reference_intent,
            },
        )

    def to_prompt_section(self) -> str:
        lines = ["## 风格上下文"]
        if self.user_constraints:
            lines.append("用户明确风格约束：")
            lines.extend(f"- {item}" for item in self.user_constraints)
        if self.matched_skills:
            lines.append("匹配到的 Skill：")
            lines.extend(f"- {name}" for name in self.matched_skills)
        if self.hard_constraints:
            lines.append("硬性视觉约束：")
            lines.extend(f"- {item}" for item in self.hard_constraints)
        if self.reference_images:
            lines.append("用户参考图片：")
            for ref in self.reference_images:
                lines.append(f"- {ref.label}: {ref.path}")
            if self.reference_intent in {"object_transfer", "subject_reference"}:
                lines.append(
                    "必须识别参考图片中的核心衣物、服装、首饰或物品，并让这些参考物品实际出现在生成图里；"
                    "不要只借用风格或把参考图当作截图插入。"
                )
            elif self.reference_intent == "composition_reference":
                lines.append(
                    "只参考参考图的构图、版式、镜头角度、画面比例或空间布局；"
                    "不要保留参考图中的具体物体，也不要把参考图当作截图插入。"
                )
            elif self.reference_intent == "scene_reference":
                lines.append(
                    "只参考参考图的场景类型、环境氛围、空间关系或地点线索；"
                    "不要保留参考图中的具体物体，也不要把参考图当作截图插入。"
                )
            elif self.reference_intent == "material_color_reference":
                lines.append(
                    "只参考参考图的材质纹理、面料质感、色彩搭配或表面细节；"
                    "不要保留参考图中的具体物体，也不要把参考图当作截图插入。"
                )
            elif self.reference_intent == "style_reference":
                lines.append(
                    "只参考参考图的风格、色调、光线、构图、材质质感或氛围；"
                    "不要保留参考图中的具体物体，也不要把参考图当作截图插入。"
                )
            else:
                lines.append(
                    "参考图用途未明确时，优先作为风格、氛围或构图参考；"
                    "不要默认迁移参考图中的具体物体，除非用户明确要求保留或迁移。"
                )
        if self.negative_constraints:
            lines.append("禁用项：")
            lines.extend(f"- {item}" for item in self.negative_constraints)
        if self.prompt_refs:
            lines.append("仓库版本化风格参考：")
            for ref in self.prompt_refs:
                lines.append(f"- 来源：{ref.source}")
                if ref.title:
                    lines.append(f"  标题：{ref.title}")
                if ref.excerpt:
                    lines.append(f"  摘要：{ref.excerpt}")
        return "\n".join(lines)

    def metadata(self) -> dict[str, Any]:
        return {
            "user_constraints": list(self.user_constraints),
            "matched_skills": list(self.matched_skills),
            "prompt_ref_sources": [ref.source for ref in self.prompt_refs],
            "reference_images": [ref.model_dump(mode="json") for ref in self.reference_images],
            "reference_intent": self.reference_intent,
            "hard_constraints": list(self.hard_constraints),
            "negative_constraints": list(self.negative_constraints),
        }

    def reference_image_inputs(self) -> list[tuple[str, Path]]:
        return [(ref.label, Path(ref.path)) for ref in self.reference_images]


def _dedupe(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _build_reference_images(values: Sequence[Any]) -> list[ReferenceImageRef]:
    refs: list[ReferenceImageRef] = []
    for index, value in enumerate(values):
        path = str(value).strip()
        if not path:
            continue
        refs.append(
            ReferenceImageRef(
                label=f"reference_{index + 1}",
                path=path,
                mime_type=mimetypes.guess_type(path)[0] or "image/jpeg",
            )
        )
    return refs


def _derive_reference_intent(
    request: Any,
    user_constraints: Sequence[str],
    reference_images: Sequence[ReferenceImageRef],
) -> str:
    if not reference_images:
        return "none"
    haystack = "\n".join(
        str(value or "")
        for value in (
            getattr(request, "topic", ""),
            getattr(request, "audience", ""),
            getattr(request, "message", ""),
            *user_constraints,
        )
    ).lower()
    if _is_object_transfer_reference(haystack):
        return "object_transfer"
    if _is_subject_reference(haystack):
        return "subject_reference"
    if _is_composition_reference(haystack):
        return "composition_reference"
    if _is_scene_reference(haystack):
        return "scene_reference"
    if _is_material_color_reference(haystack):
        return "material_color_reference"
    if _is_style_reference_only(haystack):
        return "style_reference"
    if _is_style_reference(haystack):
        return "style_reference"
    return "unspecified"


def _is_style_reference_only(haystack: str) -> bool:
    return (
        any(
            marker in haystack
            for marker in (
                "只参考",
                "仅参考",
                "只借鉴",
                "仅借鉴",
                "style only",
                "style reference only",
            )
        )
        and _is_style_reference(haystack)
        and any(
            marker in haystack
            for marker in (
                "不要求保留",
                "不需要保留",
                "不要保留",
                "不保留",
                "不要生成原图",
                "不复刻",
                "do not preserve",
                "no need to preserve",
                "do not keep",
            )
        )
    )


def _is_style_reference(haystack: str) -> bool:
    return any(
        marker in haystack
        for marker in (
            "参考风格",
            "参考色调",
            "参考光线",
            "参考构图",
            "参考氛围",
            "风格",
            "色调",
            "光线",
            "构图",
            "氛围",
            "质感",
            "style",
            "palette",
            "lighting",
            "composition",
            "mood",
            "texture",
        )
    )


def _is_composition_reference(haystack: str) -> bool:
    return any(
        marker in haystack
        for marker in (
            "composition reference",
            "layout reference",
            "framing reference",
            "参考构图",
            "参考版式",
            "参考画面比例",
            "构图比例",
            "版式",
            "画面布局",
            "镜头构图",
            "留白节奏",
        )
    )


def _is_scene_reference(haystack: str) -> bool:
    return any(
        marker in haystack
        for marker in (
            "scene reference",
            "setting reference",
            "environment reference",
            "参考场景",
            "参考环境",
            "场景参考",
            "环境氛围",
            "空间氛围",
            "室内场景",
            "户外场景",
            "咖啡馆场景",
            "地点线索",
        )
    )


def _is_material_color_reference(haystack: str) -> bool:
    return any(
        marker in haystack
        for marker in (
            "material reference",
            "color palette reference",
            "palette reference",
            "texture reference",
            "参考材质",
            "参考面料",
            "参考纹理",
            "参考颜色",
            "参考配色",
            "材质参考",
            "面料纹理",
            "颜色搭配",
            "色彩搭配",
            "材质质感",
        )
    )


def _is_object_transfer_reference(haystack: str) -> bool:
    if any(
        marker in haystack
        for marker in (
            "不迁移物体",
            "不要迁移物体",
            "不做物体迁移",
            "不要物体迁移",
            "do not transfer the object",
        )
    ):
        return False
    if any(
        marker in haystack
        for marker in (
            "strict_object_transfer",
            "object_transfer",
            "subject/object reference",
            "object reference",
            "object transfer",
            "same object",
            "transfer the object",
            "must contain the reference",
            "元素迁移",
            "物体迁移",
            "实物迁移",
            "物品迁移",
            "商品迁移",
            "主体迁移",
            "原封不动",
            "原样迁移",
            "原样搬",
            "搬到新",
            "迁移到",
            "放入新的生成图",
            "放到新的生成图",
            "放进新的生成图",
        )
    ):
        return True
    if re.search(
        r"(?:必须|需要|要)[^。；;\n]*(?:参考图|原图)[^。；;\n]*(?:放入|放到|放进|带到|迁移|搬到|包含|出现在)",
        haystack,
    ):
        return True
    return bool(
        re.search(
            r"(?:参考图|原图)[^。；;\n]*(?:里的|中的)[^。；;\n]*(?:必须|需要|要)[^。；;\n]*(?:放入|放到|放进|带到|迁移|搬到|包含|出现在)",
            haystack,
        )
    )


def _is_subject_reference(haystack: str) -> bool:
    if any(
        marker in haystack
        for marker in (
            "不保留原图",
            "不要保留原图",
            "不要求保留原图",
            "不需要保留原图",
            "不保留参考图",
            "不要保留参考图",
            "不保留主体",
            "不要保留主体",
            "不要求保留主体",
            "不需要保留主体",
            "do not preserve",
            "no need to preserve",
        )
    ):
        return False
    if any(
        marker in haystack
        for marker in (
            "preserve_reference_subject",
            "subject_reference",
            "subject reference",
            "preserve reference subject",
            "preserve the subject",
            "preserve the referenced",
            "保留参考图",
            "保留原图",
            "保留主体",
            "保持主体",
            "主体参考",
        )
    ):
        return True
    return bool(re.search(r"参考图[^。；;,\n]*(必须|需要|要)[^。；;,\n]*(出现在|出现|保留|包含)", haystack))


def _derive_hard_constraints(
    request: Any,
    user_constraints: Sequence[str],
    *,
    reference_images: Sequence[ReferenceImageRef] = (),
    reference_intent: str = "none",
) -> list[str]:
    constraints = list(user_constraints)
    image_count = getattr(request, "image_count", None)
    if image_count:
        constraints.append(f"图片数量：{image_count} 张")
    if reference_images:
        count_text = f"用户提供了 {len(reference_images)} 张参考图"
        if reference_intent == "style_reference":
            constraints.append(
                f"{count_text}；reference_role=style_reference；只参考参考图的风格、色调、光线、构图、材质质感或氛围，"
                "不要保留参考图中的具体物体。"
            )
        elif reference_intent == "object_transfer":
            constraints.append(
                f"{count_text}；reference_role=object_transfer；必须识别参考图中的目标物体、服装、首饰或商品，"
                "并把这些参考物体迁移到新的生成场景中。"
            )
        elif reference_intent == "subject_reference":
            constraints.append(
                f"{count_text}；reference_role=subject_reference；生成图片必须识别并保留参考图中的核心衣物、服装、首饰或物品，"
                "这些参考物品必须出现在生成图里，不要只借用风格。"
            )
        elif reference_intent == "composition_reference":
            constraints.append(
                f"{count_text}；reference_role=composition_reference；只参考参考图的构图、版式、镜头角度、画面比例或空间布局，"
                "不要保留参考图中的具体物体。"
            )
        elif reference_intent == "scene_reference":
            constraints.append(
                f"{count_text}；reference_role=scene_reference；只参考参考图的场景类型、环境氛围、空间关系或地点线索，"
                "不要保留参考图中的具体物体。"
            )
        elif reference_intent == "material_color_reference":
            constraints.append(
                f"{count_text}；reference_role=material_color_reference；只参考参考图的材质纹理、面料质感、色彩搭配或表面细节，"
                "不要保留参考图中的具体物体。"
            )
        else:
            constraints.append(
                f"{count_text}；reference_role=style_reference；参考用途未明确时优先作为风格、氛围或构图参考，"
                "不要默认迁移参考图中的具体物体。"
            )
    return _dedupe(constraints)


def _derive_negative_constraints(user_constraints: Sequence[str]) -> list[str]:
    negatives = [
        "不要生成登录弹窗、应用界面、app screenshots、工具报错、研究限制说明或 session 状态卡片",
        "不要把研究诊断信息、内部审核意见、提示词模板说明画进图片",
        "除非当前图片任务明确要求文字海报、信息图或文字卡，否则不要生成标题、副标题、大段文字或任何可读文字；文字内容交给飞书正文承载",
    ]
    joined = " ".join(user_constraints)
    if any(marker in joined for marker in ("不要人物", "无人物", "不需要人物", "no people")):
        negatives.append("不要人物、模特、人台或拟人化身体部位")
    if any(
        marker in joined.lower()
        for marker in ("无文字", "不要文字", "不需要文字", "no text", "text-free")
    ):
        negatives.append("不要生成任何可见文字、标题、标签、手写字、菜单字、路牌字或装饰性字符")
    if any(
        marker in joined.lower()
        for marker in ("无logo", "不要logo", "不要 logo", "no logo", "no logos", "watermark", "水印")
    ):
        negatives.append("不要生成任何品牌 logo、伪造商标、水印或可识别商业标识")
    return _dedupe(negatives)


def _load_skill_prompt_refs(skill: SkillSpec) -> list[StylePromptRef]:
    refs_dir = skill.path / "references"
    source_files = sorted(refs_dir.glob("*.md")) if refs_dir.exists() else []
    if not source_files:
        source_files = [skill.path / "SKILL.md"]

    refs: list[StylePromptRef] = []
    for source_file in source_files:
        if not source_file.exists() or not source_file.is_file():
            continue
        refs.append(_build_prompt_ref(source_file, title_fallback=skill.name, tags=[skill.name]))
    return refs


def _build_prompt_ref(
    source_file: Path,
    *,
    title_fallback: str = "",
    tags: Sequence[str] = (),
) -> StylePromptRef:
    text = source_file.read_text(encoding="utf-8", errors="ignore")
    return StylePromptRef(
        source=_normalize_source(source_file),
        title=_extract_title(text) or title_fallback,
        excerpt=_compact_excerpt(text),
        tags=list(tags),
    )


def _normalize_source(path: Path) -> str:
    return path.resolve().as_posix()


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _compact_excerpt(text: str, *, max_chars: int = 800) -> str:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("---")
    ]
    excerpt = " ".join(lines)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 1].rstrip() + "…"
