from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .style_context import StyleContext


class ContentRoute(str, Enum):
    IMAGE_POST = "image_post"
    ARTICLE_POST = "article_post"
    VIDEO_POST = "video_post"


class ConversationRequest(BaseModel):
    topic: str
    audience: str
    message: str = ""
    route_hint: ContentRoute | None = None
    style_constraints: list[str] = Field(default_factory=list)
    image_count: int | None = None


class WorkflowPlan(BaseModel):
    route: ContentRoute
    matched_skills: list[str] = Field(default_factory=list)
    rationale: str = ""
    style_constraints: list[str] = Field(default_factory=list)
    style_context: StyleContext | None = None
