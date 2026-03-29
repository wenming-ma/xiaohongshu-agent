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


class RecoveryRecord(BaseModel):
    attempt_number: int = 0
    recovery_number: int = 0
    phase: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback_excerpt: str = ""
    traceback_log_path: str = ""
    head_before: str = ""
    status: str = ""
    reason: str = ""
    fix_summary: str = ""
    validation_notes: str = ""
    restarted: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AttemptRecord(BaseModel):
    attempt_number: int
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    objective_stage: str = "PASS"
    objective_summary: str = ""
    controller_action: str = ""
    controller_reason: str = ""
    fix_description: str = ""
    exit_code: int | None = None
    duration_seconds: float | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    stdout_log_path: str = ""
    stderr_log_path: str = ""
    validation_label: str = ""
    validator_verdict: str = ""
    validator_reason: str = ""
    validator_execution_record: str = ""
    validator_next_focus: str = ""
    controller_memory_path: str = ""
    validator_memory_path: str = ""
    output_dir: str = ""
    video_path: str = ""
    user_feedback: str = ""
    pull_request_requested: bool = False
    pull_request_title: str = ""
    pull_request_body: str = ""
    pull_request_base_branch: str = ""
    pull_request_draft: bool = False
    pull_request_url: str = ""
    pull_request_error: str = ""
    files_modified: list[str] = Field(default_factory=list)
    committed: bool = False
    commit_hash: str = ""
    head_before: str = ""
    head_after: str = ""
    rollback_to: str = ""
    rolled_back: bool = False
    workers: list[WorkerInvocation] = Field(default_factory=list)


class ClusterState(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target_command: str = ""
    attempts: list[AttemptRecord] = Field(default_factory=list)
    current_objective_stage: str = "PASS"
    current_objective: str = "Make the target command pass."
    current_controller_reason: str = ""
    current_user_feedback: str = ""
    current_review_video_path: str = ""
    pending_pull_request_title: str = ""
    pending_pull_request_body: str = ""
    pending_pull_request_base_branch: str = ""
    pending_pull_request_draft: bool = False
    pull_request_url: str = ""
    pull_request_error: str = ""
    best_success_duration_seconds: float | None = None
    current_branch: str = ""
    original_branch: str = ""
    source_repo_root: str = ""
    worktree_root: str = ""
    controller_memory_file: str = ""
    validator_memory_file: str = ""
    recovery_history: list[RecoveryRecord] = Field(default_factory=list)
    source_head: str = ""
    source_dirty: bool = False
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

        lines: list[str] = []
        for attempt in self.attempts[-max_entries:]:
            status = "ROLLED_BACK" if attempt.rolled_back else ("COMMITTED" if attempt.committed else "NO_CHANGE")
            lines.append(
                f"Attempt #{attempt.attempt_number} [{status}] action={attempt.controller_action or 'n/a'}\n"
                f"  Objective: {attempt.objective_stage} - {attempt.objective_summary[:120]}\n"
                f"  Controller: {attempt.controller_reason[:160]}\n"
                f"  Result: exit={_format_exit_code(attempt.exit_code)}, duration={_format_duration(attempt.duration_seconds)}, verdict={attempt.validator_verdict or 'n/a'}\n"
                f"  Validator: {attempt.validator_reason[:180]}\n"
                f"  User feedback: {(attempt.user_feedback or 'n/a')[:180]}\n"
                f"  Fix: {attempt.fix_description[:200]}\n"
                f"  Files: {', '.join(attempt.files_modified) or 'none'}"
            )
        return "\n\n".join(lines)


def _format_duration(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}s"


def _format_exit_code(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)
