from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.orchestration.conversation import ContentRoute
from src.orchestration.schemas import ArtifactRef, ResultEnvelope

EventSource = Literal["feishu", "system"]
EventKind = Literal["text", "image", "button", "form", "control", "timer"]
EventPriority = Literal["asap", "when_idle"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentOSEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    source: EventSource = "feishu"
    kind: EventKind
    text: str = ""
    image_path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: EventPriority = "asap"
    created_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def image(
        cls,
        path: str,
        *,
        caption: str = "",
        priority: EventPriority = "asap",
    ) -> "AgentOSEvent":
        return cls(kind="image", text=caption, image_path=path, priority=priority)

    @classmethod
    def control(cls, action: str) -> "AgentOSEvent":
        return cls(
            kind="control",
            text=action,
            payload={"action": action},
            priority="asap",
        )


def _make_text_event(
    cls: type[AgentOSEvent],
    text: str,
    *,
    priority: EventPriority = "asap",
) -> AgentOSEvent:
    return cls(kind="text", text=text, priority=priority)


AgentOSEvent.text = classmethod(_make_text_event)  # type: ignore[attr-defined]


class ResearchRunOptionsSpec(BaseModel):
    max_items: int | None = None
    depth: Literal["fast", "standard", "deep"] | None = None


class GroupingRunOptionsSpec(BaseModel):
    target_group_count: int | None = None
    single_item_per_image: bool | None = None


class ImageRunOptionsSpec(BaseModel):
    count: int | None = None
    model: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    reference_mode: str | None = None
    concurrency: int | None = None


class ReviewRunOptionsSpec(BaseModel):
    strictness: Literal["low", "standard", "high"] | None = None


class RunOptions(BaseModel):
    research: ResearchRunOptionsSpec = Field(default_factory=ResearchRunOptionsSpec)
    grouping: GroupingRunOptionsSpec = Field(default_factory=GroupingRunOptionsSpec)
    image: ImageRunOptionsSpec = Field(default_factory=ImageRunOptionsSpec)
    review: ReviewRunOptionsSpec = Field(default_factory=ReviewRunOptionsSpec)


class DeliverySpec(BaseModel):
    target: Literal["feishu"] = "feishu"
    include_artifacts: bool = True
    chat_id: str | None = None


class TaskStepSpec(BaseModel):
    step_id: str
    tool_name: str
    input_refs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    parallel_group: str | None = None


class TaskRunSpec(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    objective: str
    route: ContentRoute | None = None
    topic: str | None = None
    audience: str | None = None
    user_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    style_constraints: list[str] = Field(default_factory=list)
    reference_images: list[ArtifactRef] = Field(default_factory=list)
    selected_skills: list[str] = Field(default_factory=list)
    selected_prompt_templates: list[str] = Field(default_factory=list)
    run_options: RunOptions = Field(default_factory=RunOptions)
    steps: list[TaskStepSpec] = Field(default_factory=list)
    delivery: DeliverySpec = Field(default_factory=DeliverySpec)


class AgentToolResult(BaseModel):
    envelope: ResultEnvelope[Any]
    produced_refs: list[str] = Field(default_factory=list)
    next_suggestions: list[str] = Field(default_factory=list)
