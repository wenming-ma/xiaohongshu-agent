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
