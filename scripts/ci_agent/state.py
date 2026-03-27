from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    tool_name: str
    tool_input: dict = Field(default_factory=dict)
    result_summary: str = ""
    success: bool = True


class WorkerInvocation(BaseModel):
    worker_type: str
    prompt_summary: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    final_text: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AttemptRecord(BaseModel):
    attempt_number: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    log_files_read: list[str] = Field(default_factory=list)
    diagnosis: str = ""
    diagnosis_category: str = ""
    fix_description: str = ""
    files_modified: list[str] = Field(default_factory=list)
    committed: bool = False
    commit_hash: str = ""
    rolled_back: bool = False
    workers: list[WorkerInvocation] = Field(default_factory=list)


class ClusterState(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target_command: str = ""
    attempts: list[AttemptRecord] = Field(default_factory=list)
    current_branch: str = ""
    original_branch: str = ""
    status: str = "running"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ClusterState:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def format_attempt_history(self, max_entries: int = 10) -> str:
        if not self.attempts:
            return "No previous attempts."
        recent = self.attempts[-max_entries:]
        lines = []
        for a in recent:
            status = "ROLLED_BACK" if a.rolled_back else ("COMMITTED" if a.committed else "NO_CHANGE")
            lines.append(
                f"Attempt #{a.attempt_number} [{status}] exit={a.exit_code}\n"
                f"  Category: {a.diagnosis_category}\n"
                f"  Diagnosis: {a.diagnosis[:300]}\n"
                f"  Fix: {a.fix_description[:200]}\n"
                f"  Files: {', '.join(a.files_modified) or 'none'}"
            )
        return "\n\n".join(lines)
