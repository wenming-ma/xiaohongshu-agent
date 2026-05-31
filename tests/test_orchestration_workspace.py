from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from src.orchestration.schemas import ArtifactRef, ResultEnvelope
from src.orchestration.workspace import WorkflowWorkspace


class DemoPayload(BaseModel):
    topic: str
    count: int


def test_workflow_workspace_persists_envelopes_and_manifest(tmp_path: Path) -> None:
    workspace = WorkflowWorkspace.create(
        root_dir=tmp_path,
        run_id="run-42",
        route="image_post",
        topic="纯色背景穿搭",
        audience="通勤女生",
    )
    envelope = ResultEnvelope[DemoPayload].success(
        agent_name="research_agent",
        payload=DemoPayload(topic="纯色背景穿搭", count=2),
        summary="完成调研",
        run_id="run-42",
        step_id="research",
    )

    artifact = workspace.save_envelope(envelope, label="research")

    assert artifact.artifact_type == "json"
    assert artifact.label == "research"
    assert Path(artifact.path).exists()

    manifest = workspace.load_manifest()
    assert manifest.run_id == "run-42"
    assert manifest.route == "image_post"
    assert manifest.topic == "纯色背景穿搭"
    assert manifest.audience == "通勤女生"
    assert len(manifest.steps) == 1
    assert manifest.steps[0].step_id == "research"
    assert manifest.steps[0].agent_name == "research_agent"
    assert manifest.steps[0].artifacts[0].path == artifact.path


def test_workflow_workspace_can_attach_artifacts_to_existing_step(tmp_path: Path) -> None:
    workspace = WorkflowWorkspace.create(
        root_dir=tmp_path,
        run_id="run-99",
        route="image_post",
        topic="纯色背景穿搭",
        audience="通勤女生",
    )
    envelope = ResultEnvelope[DemoPayload].success(
        agent_name="image_generation_agent",
        payload=DemoPayload(topic="封面图", count=1),
        summary="图片生成完成",
        run_id="run-99",
        step_id="image-0",
    )
    workspace.save_envelope(envelope, label="image-0")

    image_path = workspace.run_dir / "generated" / "cover.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-image")
    image_artifact = ArtifactRef(
        artifact_type="image",
        label="cover",
        path=str(image_path),
        mime_type="image/png",
    )

    workspace.attach_artifacts(step_id="image-0", artifacts=[image_artifact])

    manifest = workspace.load_manifest()
    assert len(manifest.steps) == 1
    assert manifest.steps[0].step_id == "image-0"
    assert len(manifest.steps[0].artifacts) == 2
    assert manifest.steps[0].artifacts[-1].path == str(image_path)
