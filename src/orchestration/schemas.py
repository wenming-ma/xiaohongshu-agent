from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

PayloadT = TypeVar("PayloadT")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EnvelopeStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ArtifactRef(BaseModel):
    artifact_type: str
    label: str
    path: str
    mime_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowInvocation(BaseModel):
    """Structured task call produced by the main Agent before graph execution."""

    objective: str
    route: str | None = None
    topic: str | None = None
    audience: str | None = None
    selected_skills: list[str] = Field(default_factory=list)
    selected_prompt_templates: list[str] = Field(default_factory=list)
    user_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    run_options: Any | None = None
    delivery: dict[str, Any] = Field(default_factory=lambda: {"target": "feishu"})

    @classmethod
    def from_task_spec(cls, spec: Any) -> "WorkflowInvocation":
        constraints = list(getattr(spec, "constraints", []) or [])
        constraints.extend(str(item) for item in (getattr(spec, "style_constraints", []) or []))
        route_value = getattr(spec, "route", None)
        if hasattr(route_value, "value"):
            route_value = route_value.value
        return cls(
            objective=str(getattr(spec, "objective", "") or ""),
            route=str(route_value or "") or None,
            topic=getattr(spec, "topic", None),
            audience=getattr(spec, "audience", None),
            selected_skills=list(getattr(spec, "selected_skills", []) or []),
            selected_prompt_templates=list(getattr(spec, "selected_prompt_templates", []) or []),
            constraints=constraints,
            artifacts=list(getattr(spec, "reference_images", []) or []),
            run_options=getattr(spec, "run_options", None),
            delivery=(
                getattr(spec, "delivery").model_dump(mode="json")
                if getattr(spec, "delivery", None) is not None
                else {"target": "feishu"}
            ),
        )


class WorkflowState(BaseModel):
    """Application-level graph state shared by module nodes."""

    invocation: WorkflowInvocation
    run_id: str
    workspace_dir: str
    module_results: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_invocation(
        cls,
        invocation: WorkflowInvocation,
        *,
        run_id: str,
        workspace_dir: str,
    ) -> "WorkflowState":
        return cls(invocation=invocation, run_id=run_id, workspace_dir=workspace_dir)


class WorkflowRunContext(BaseModel):
    """Small execution metadata object passed around orchestration helpers."""

    run_id: str
    workspace_dir: str
    chat_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageReferenceRole(str, Enum):
    STYLE_REFERENCE = "style_reference"
    SUBJECT_REFERENCE = "subject_reference"
    OBJECT_TRANSFER = "object_transfer"
    COMPOSITION_REFERENCE = "composition_reference"
    SCENE_REFERENCE = "scene_reference"
    MATERIAL_COLOR_REFERENCE = "material_color_reference"


class ReferenceImagePlan(BaseModel):
    label: str
    path: str
    role: ImageReferenceRole = ImageReferenceRole.STYLE_REFERENCE
    artifact: ArtifactRef | None = None
    notes: str = ""


class SingleImageTaskPlan(BaseModel):
    image_type: str
    group_title: str
    indices: list[int] = Field(default_factory=list)
    description: str = ""
    generation_mode: Literal[
        "text_to_image",
        "style_reference_generation",
        "subject_preserving_generation",
        "object_transfer",
        "variation",
        "composite_or_layout",
    ] = "text_to_image"
    reference_images: list[ReferenceImagePlan] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    selected_skills: list[str] = Field(default_factory=list)
    selected_prompt_templates: list[str] = Field(default_factory=list)
    qa_rules: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_group_payload(self) -> dict[str, object]:
        return {
            "title": self.group_title,
            "indices": list(self.indices),
            "image_type": self.image_type,
            "desc": self.description,
            "generation_mode": self.generation_mode,
            "reference_images": [reference.model_dump(mode="json") for reference in self.reference_images],
            "hard_constraints": list(self.hard_constraints),
            "qa_rules": list(self.qa_rules),
        }


class ImageTaskPlan(BaseModel):
    """Plan for the whole image set generated by the image planner node."""

    tasks: list[SingleImageTaskPlan] = Field(default_factory=list)
    summary: str = ""

    @classmethod
    def plan_from_groups(
        cls,
        *,
        invocation: WorkflowInvocation,
        groups: "GroupingResult",
        requested_image_count: int | None,
        single_item_per_image: bool,
        max_auto_images: int | None,
        reference_analysis: list[ReferenceImagePlan] | None = None,
    ) -> "ImageTaskPlan":
        group_items = list(groups.groups)
        group_payloads = cls._group_payloads(
            group_items=group_items,
            requested_image_count=requested_image_count,
            single_item_per_image=single_item_per_image,
            max_auto_images=max_auto_images,
        )
        references = list(reference_analysis) if reference_analysis is not None else cls.reference_plans_from_invocation(invocation)
        mode = cls._generation_mode(references)
        hard_constraints = list(dict.fromkeys(invocation.constraints))
        qa_rules = cls._qa_rules(references=references, hard_constraints=hard_constraints)
        tasks = [
            SingleImageTaskPlan(
                image_type=str(group["image_type"]),
                group_title=str(group["title"]),
                indices=list(group.get("indices") or []),
                description=str(group.get("desc") or ""),
                generation_mode=mode,
                reference_images=references,
                hard_constraints=hard_constraints,
                preferences=list(invocation.preferences),
                selected_skills=list(invocation.selected_skills),
                selected_prompt_templates=list(invocation.selected_prompt_templates),
                qa_rules=qa_rules,
                metadata={"objective": invocation.objective, "route": invocation.route},
            )
            for group in group_payloads
        ]
        return cls(tasks=tasks, summary=f"规划 {len(tasks)} 张图片")

    @staticmethod
    def _group_payloads(
        *,
        group_items: list["GroupingItem"],
        requested_image_count: int | None,
        single_item_per_image: bool,
        max_auto_images: int | None,
    ) -> list[dict[str, object]]:
        if single_item_per_image and group_items:
            payloads: list[dict[str, object]] = [
                {
                    "title": group_items[0].title,
                    "indices": list(group_items[0].indices),
                    "image_type": "cover",
                    "desc": f"封面图 - 单套展示：{group_items[0].title}",
                }
            ]
            payloads.extend(
                {
                    "title": group.title,
                    "indices": list(group.indices),
                    "image_type": f"detail_{index}",
                }
                for index, group in enumerate(group_items[1:], start=1)
            )
        else:
            if requested_image_count is not None and 0 < requested_image_count <= len(group_items):
                payloads = [
                    {
                        "title": group_items[0].title,
                        "indices": list(group_items[0].indices),
                        "image_type": "cover",
                        "desc": f"封面图 - 语义分组：{group_items[0].title}",
                    },
                    *[
                        {
                            "title": group.title,
                            "indices": list(group.indices),
                            "image_type": f"detail_{index}",
                        }
                        for index, group in enumerate(group_items[1:], start=1)
                    ],
                ]
            else:
                payloads = [
                    {"title": "封面", "indices": [], "image_type": "cover"},
                    *[
                    {
                        "title": group.title,
                        "indices": list(group.indices),
                        "image_type": f"detail_{index}",
                    }
                    for index, group in enumerate(group_items, start=1)
                    ],
                ]

        if requested_image_count is not None:
            target_count = max(1, min(requested_image_count, 20))
            while len(payloads) < target_count:
                image_number = len(payloads) + 1
                image_type = "cover" if not payloads else f"detail_{len(payloads)}"
                if single_item_per_image:
                    title = f"第{image_number}张单套穿搭"
                    desc = (
                        f"{'封面图' if image_number == 1 else '详情图'} - "
                        f"用户明确要求的第{image_number}张单套展示图；"
                        "请根据用户原始要求、正文中的对应图号和风格约束生成，"
                        "不要复用前面图片。"
                    )
                else:
                    title = f"第{image_number}张补充画面"
                    desc = (
                        f"{'封面图' if image_number == 1 else '详情图'} - "
                        f"用户明确要求的第{image_number}张图片；"
                        "当研究或分组数量不足时，请根据用户原始要求、正文、当前主题和风格约束生成一个新的独立画面，"
                        "不要复用前面图片，也不要生成研究限制、登录提示或系统诊断文字。"
                    )
                payloads.append({"title": title, "indices": [], "image_type": image_type, "desc": desc})
            return payloads[:target_count]

        if max_auto_images is not None:
            target_count = max(1, min(max_auto_images, 20))
            return payloads[:target_count]
        return payloads

    @staticmethod
    def reference_plans_from_invocation(invocation: WorkflowInvocation) -> list[ReferenceImagePlan]:
        return [
            ReferenceImagePlan(
                label=artifact.label,
                path=artifact.path,
                role=ImageTaskPlan._reference_role_for_artifact(invocation=invocation, artifact=artifact),
                artifact=artifact,
                notes=str(artifact.metadata.get("notes") or artifact.metadata.get("description") or ""),
            )
            for artifact in invocation.artifacts
            if artifact.artifact_type == "image"
        ]

    @staticmethod
    def _reference_role_for_artifact(
        *,
        invocation: WorkflowInvocation,
        artifact: ArtifactRef,
    ) -> ImageReferenceRole:
        metadata_role = (
            artifact.metadata.get("reference_role")
            or artifact.metadata.get("image_reference_role")
            or artifact.metadata.get("role")
        )
        if metadata_role:
            return ImageTaskPlan._normalize_reference_role(str(metadata_role))

        constraints = {constraint.lower() for constraint in invocation.constraints}
        haystack = "\n".join(
            [
                invocation.objective,
                *(invocation.constraints or []),
                *(invocation.user_requirements or []),
                str(artifact.metadata.get("notes") or ""),
                str(artifact.metadata.get("description") or ""),
            ]
        ).lower()
        style_only = (
            any(marker in haystack for marker in ("只参考", "仅参考", "style only", "style reference only"))
            and any(marker in haystack for marker in ("风格", "色调", "光线", "构图", "氛围", "style", "palette", "lighting"))
            and any(marker in haystack for marker in ("不要求保留", "不需要保留", "不保留", "do not preserve", "no need to preserve"))
        )
        if style_only:
            return ImageReferenceRole.STYLE_REFERENCE
        if (
            "strict_object_transfer" in constraints
            or "object_transfer" in constraints
            or any(
                marker in haystack
                for marker in (
                    "subject/object reference",
                    "object reference",
                    "object transfer",
                    "same object",
                    "transfer the object",
                    "must contain the reference",
                    "元素迁移",
                    "物体迁移",
                    "主体迁移",
                    "原封不动",
                    "原样迁移",
                    "原样搬",
                    "搬到新",
                    "迁移到",
                )
            )
        ):
            return ImageReferenceRole.OBJECT_TRANSFER
        if (
            "preserve_reference_subject" in constraints
            or "subject_reference" in constraints
            or any(
                marker in haystack
                for marker in (
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
            )
        ):
            return ImageReferenceRole.SUBJECT_REFERENCE
        if "composition_reference" in constraints:
            return ImageReferenceRole.COMPOSITION_REFERENCE
        if "scene_reference" in constraints:
            return ImageReferenceRole.SCENE_REFERENCE
        if "material_color_reference" in constraints:
            return ImageReferenceRole.MATERIAL_COLOR_REFERENCE
        return ImageReferenceRole.STYLE_REFERENCE

    @staticmethod
    def _normalize_reference_role(value: str) -> ImageReferenceRole:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "style": ImageReferenceRole.STYLE_REFERENCE,
            "style_reference": ImageReferenceRole.STYLE_REFERENCE,
            "subject": ImageReferenceRole.SUBJECT_REFERENCE,
            "subject_reference": ImageReferenceRole.SUBJECT_REFERENCE,
            "preserve_subject": ImageReferenceRole.SUBJECT_REFERENCE,
            "object": ImageReferenceRole.OBJECT_TRANSFER,
            "object_transfer": ImageReferenceRole.OBJECT_TRANSFER,
            "strict_object_transfer": ImageReferenceRole.OBJECT_TRANSFER,
            "composition": ImageReferenceRole.COMPOSITION_REFERENCE,
            "composition_reference": ImageReferenceRole.COMPOSITION_REFERENCE,
            "scene": ImageReferenceRole.SCENE_REFERENCE,
            "scene_reference": ImageReferenceRole.SCENE_REFERENCE,
            "material": ImageReferenceRole.MATERIAL_COLOR_REFERENCE,
            "material_color": ImageReferenceRole.MATERIAL_COLOR_REFERENCE,
            "material_color_reference": ImageReferenceRole.MATERIAL_COLOR_REFERENCE,
        }
        try:
            return ImageReferenceRole(normalized)
        except ValueError:
            return aliases.get(normalized, ImageReferenceRole.STYLE_REFERENCE)

    @staticmethod
    def _generation_mode(references: list[ReferenceImagePlan]) -> str:
        roles = {reference.role for reference in references}
        if ImageReferenceRole.OBJECT_TRANSFER in roles:
            return "object_transfer"
        if ImageReferenceRole.SUBJECT_REFERENCE in roles:
            return "subject_preserving_generation"
        if references:
            return "style_reference_generation"
        return "text_to_image"

    @staticmethod
    def _qa_rules(
        *,
        references: list[ReferenceImagePlan],
        hard_constraints: list[str],
    ) -> list[str]:
        rules = ["must_match_current_group"]
        roles = {reference.role for reference in references}
        if ImageReferenceRole.OBJECT_TRANSFER in roles or ImageReferenceRole.SUBJECT_REFERENCE in roles:
            rules.append("must_preserve_reference_subjects")
        if "no_people" in {constraint.lower() for constraint in hard_constraints}:
            rules.append("must_not_include_people")
        return rules


class DeliveryTextBlock(BaseModel):
    label: str
    text: str


class DeliveryPackage(BaseModel):
    route: str
    title: str = ""
    summary: str = ""
    text_blocks: list[DeliveryTextBlock] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroupingItem(BaseModel):
    title: str
    indices: list[int] = Field(default_factory=list)
    rationale: str = ""


class GroupingResult(BaseModel):
    groups: list[GroupingItem] = Field(default_factory=list)


class ResultEnvelope(BaseModel, Generic[PayloadT]):
    agent_name: str
    result_type: str
    status: Literal["success", "error"]
    payload: PayloadT | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    summary: str = ""
    run_id: str
    step_id: str
    created_at: datetime = Field(default_factory=_utcnow)
    error_message: str | None = None

    @classmethod
    def _result_type_name(cls, payload: PayloadT | None = None) -> str:
        meta = getattr(cls, "__pydantic_generic_metadata__", None) or {}
        args = meta.get("args") or ()
        if args:
            first = args[0]
            if hasattr(first, "__name__"):
                return first.__name__
            return str(first)
        if payload is not None:
            return type(payload).__name__
        return "UnknownPayload"

    @classmethod
    def success(
        cls,
        *,
        agent_name: str,
        payload: PayloadT,
        summary: str,
        run_id: str,
        step_id: str,
        artifacts: list[ArtifactRef] | None = None,
    ) -> "ResultEnvelope[PayloadT]":
        return cls(
            agent_name=agent_name,
            result_type=cls._result_type_name(payload),
            status=EnvelopeStatus.SUCCESS.value,
            payload=payload,
            artifacts=artifacts or [],
            summary=summary,
            run_id=run_id,
            step_id=step_id,
        )

    @classmethod
    def error(
        cls,
        *,
        agent_name: str,
        summary: str,
        error_message: str,
        run_id: str,
        step_id: str,
        artifacts: list[ArtifactRef] | None = None,
    ) -> "ResultEnvelope[PayloadT]":
        return cls(
            agent_name=agent_name,
            result_type=cls._result_type_name(None),
            status=EnvelopeStatus.ERROR.value,
            payload=None,
            artifacts=artifacts or [],
            summary=summary,
            run_id=run_id,
            step_id=step_id,
            error_message=error_message,
        )
