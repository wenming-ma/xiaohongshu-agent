from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from src.orchestration.schemas import ArtifactRef, ResultEnvelope


class DemoPayload(BaseModel):
    topic: str
    count: int


def test_result_envelope_success_infers_result_type_and_serializes_payload() -> None:
    payload = DemoPayload(topic="纯色背景穿搭", count=3)
    artifact = ArtifactRef(
        artifact_type="json",
        label="research",
        path=str(Path("output") / "research.json"),
        mime_type="application/json",
    )

    envelope = ResultEnvelope[DemoPayload].success(
        agent_name="research_agent",
        payload=payload,
        summary="完成调研",
        run_id="run-1",
        step_id="research",
        artifacts=[artifact],
    )

    assert envelope.status == "success"
    assert envelope.result_type == "DemoPayload"
    assert envelope.payload == payload
    assert envelope.artifacts == [artifact]

    dumped = envelope.model_dump(mode="json")
    assert dumped["payload"]["topic"] == "纯色背景穿搭"
    assert dumped["artifacts"][0]["artifact_type"] == "json"


def test_result_envelope_error_requires_error_message_and_allows_empty_payload() -> None:
    envelope = ResultEnvelope[DemoPayload].error(
        agent_name="image_generation_agent",
        summary="图片生成失败",
        error_message="provider timeout",
        run_id="run-2",
        step_id="image-1",
    )

    assert envelope.status == "error"
    assert envelope.payload is None
    assert envelope.error_message == "provider timeout"
    assert envelope.result_type == "DemoPayload"
