from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.utils.file_ops import load_json, save_json

from .schemas import ArtifactRef, ResultEnvelope, WorkflowInvocation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ManifestStep(BaseModel):
    step_id: str
    agent_name: str
    result_type: str
    status: str
    summary: str = ""
    envelope_path: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkspaceManifest(BaseModel):
    run_id: str
    route: str
    topic: str = ""
    audience: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    steps: list[ManifestStep] = Field(default_factory=list)


class WorkflowWorkspace:
    def __init__(self, *, run_dir: Path, manifest_path: Path, manifest: WorkspaceManifest):
        self.run_dir = run_dir
        self.manifest_path = manifest_path
        self._manifest = manifest

    @classmethod
    def create(
        cls,
        *,
        root_dir: Path,
        run_id: str,
        route: str,
        topic: str,
        audience: str,
    ) -> "WorkflowWorkspace":
        run_dir = root_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "steps").mkdir(parents=True, exist_ok=True)
        manifest = WorkspaceManifest(
            run_id=run_id,
            route=route,
            topic=topic,
            audience=audience,
        )
        manifest_path = run_dir / "manifest.json"
        save_json(manifest_path, manifest.model_dump(mode="json"))
        return cls(run_dir=run_dir, manifest_path=manifest_path, manifest=manifest)

    def load_manifest(self) -> WorkspaceManifest:
        data = load_json(self.manifest_path)
        self._manifest = WorkspaceManifest.model_validate(data)
        return self._manifest

    def save_envelope(
        self,
        envelope: ResultEnvelope[Any],
        *,
        label: str,
    ) -> ArtifactRef:
        step_path = self.run_dir / "steps" / f"{envelope.step_id}.json"
        save_json(step_path, envelope.model_dump(mode="json"))
        artifact = ArtifactRef(
            artifact_type="json",
            label=label,
            path=str(step_path),
            mime_type="application/json",
            metadata={
                "agent_name": envelope.agent_name,
                "result_type": envelope.result_type,
            },
        )

        step = ManifestStep(
            step_id=envelope.step_id,
            agent_name=envelope.agent_name,
            result_type=envelope.result_type,
            status=envelope.status,
            summary=envelope.summary,
            envelope_path=str(step_path),
            artifacts=[artifact, *envelope.artifacts],
        )
        self._upsert_step(step)
        return artifact

    def save_invocation(self, invocation: WorkflowInvocation) -> ArtifactRef:
        envelope = ResultEnvelope[WorkflowInvocation].success(
            agent_name="main_agent",
            payload=invocation,
            summary=invocation.objective,
            run_id=self._manifest.run_id,
            step_id="workflow_invocation",
        )
        return self.save_envelope(envelope, label="workflow_invocation")

    def attach_artifacts(self, *, step_id: str, artifacts: list[ArtifactRef]) -> None:
        manifest = self.load_manifest()
        for index, step in enumerate(manifest.steps):
            if step.step_id == step_id:
                updated = step.model_copy(
                    update={
                        "artifacts": [*step.artifacts, *artifacts],
                        "updated_at": _utcnow(),
                    }
                )
                manifest.steps[index] = updated
                self._manifest = manifest
                self._persist_manifest()
                return
        raise ValueError(f"Step not found in manifest: {step_id}")

    def _upsert_step(self, step: ManifestStep) -> None:
        manifest = self.load_manifest()
        for index, existing in enumerate(manifest.steps):
            if existing.step_id == step.step_id:
                manifest.steps[index] = step
                self._manifest = manifest
                self._persist_manifest()
                return
        manifest.steps.append(step)
        self._manifest = manifest
        self._persist_manifest()

    def _persist_manifest(self) -> None:
        save_json(self.manifest_path, self._manifest.model_dump(mode="json"))
