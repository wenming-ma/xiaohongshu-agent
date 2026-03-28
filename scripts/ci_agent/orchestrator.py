from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from .agent_runtime import ControllerCycleOutcome, DeepAgentRuntime, ValidatorRecord
from .config import ClusterConfig
from .state import AttemptRecord, ClusterState

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: ClusterConfig, agent_runtime: DeepAgentRuntime | None = None):
        self.config = config
        self.state = ClusterState(
            session_id=config.session_id,
            target_command=config.target_command,
            source_repo_root=str(config.project_root),
            worktree_root=str(config.worktree_root),
            validator_memory_file=str(config.validator_memory_file),
        )
        self._agent_runtime = agent_runtime

    async def run(self) -> bool:
        self._init_source_git_state()
        self._ensure_isolated_worktree()
        self._ensure_runtime_paths()

        if self._agent_runtime is None:
            self._agent_runtime = DeepAgentRuntime(self.config)

        consecutive_rollbacks = 0
        start_attempt = len(self.state.attempts) + 1

        for attempt_num in range(start_attempt, self.config.max_attempts + 1):
            logger.info("=" * 60)
            logger.info("ATTEMPT #%d / %d", attempt_num, self.config.max_attempts)
            logger.info("=" * 60)

            head_before = self._rev_parse(self.config.worktree_root, "HEAD")
            outcome = await self._agent_runtime.run_controller_cycle(
                self._build_controller_prompt(attempt_num, head_before),
                attempt_number=attempt_num,
            )
            record = self._record_attempt(attempt_num, head_before, outcome)
            self._capture_git_effects(record)
            self._apply_state_from_outcome(outcome, record)

            if record.exit_code == 0:
                self._update_best_success_duration(record.duration_seconds)

            if outcome.action == "ROLLBACK":
                logger.warning("Controller requested rollback for attempt #%d", attempt_num)
                if not self._rollback_to(head_before):
                    logger.error("Could not roll back isolated worktree to %s", head_before)
                    self._finish_with_status("stuck", record)
                    return False
                record.rolled_back = True
                record.rollback_to = head_before
                consecutive_rollbacks += 1
                self._agent_runtime.note_rollback(
                    attempt_number=attempt_num,
                    rollback_to=head_before,
                    reason=record.validator_reason or record.controller_reason,
                )
                if consecutive_rollbacks >= self.config.max_consecutive_rollbacks:
                    logger.error(
                        "Max consecutive rollbacks (%d) reached",
                        self.config.max_consecutive_rollbacks,
                    )
                    self._finish_with_status("stuck", record)
                    return False
            else:
                consecutive_rollbacks = 0

            if outcome.action == "DONE":
                if record.exit_code == 0:
                    logger.info("Controller ended the loop with a passing validated state")
                    self._finish_with_status("success", record)
                    return True
                logger.error("Controller stopped but the latest validated state is not passing")
                self._finish_with_status("stuck", record)
                return False

            self.state.attempts.append(record)
            self.state.save(self.config.state_file)

            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)

        logger.error("Max attempts (%d) exhausted", self.config.max_attempts)
        self.state.status = "exhausted"
        self.state.save(self.config.state_file)
        return False

    def _record_attempt(
        self,
        attempt_num: int,
        head_before: str,
        outcome: ControllerCycleOutcome,
    ) -> AttemptRecord:
        record = AttemptRecord(
            attempt_number=attempt_num,
            head_before=head_before,
            objective_stage=outcome.objective_stage,
            objective_summary=outcome.objective,
            controller_action=outcome.action,
            controller_reason=outcome.reason,
            fix_description=outcome.fix_summary,
            validator_memory_path=str(self.config.validator_memory_file),
            workers=outcome.workers,
        )
        self._record_validator_details(record, outcome.latest_validator_record)
        return record

    def _record_validator_details(self, record: AttemptRecord, validator_record: ValidatorRecord) -> None:
        run = validator_record.latest_validation
        record.exit_code = run.exit_code
        record.duration_seconds = run.duration_seconds
        record.stdout_tail = run.stdout_excerpt
        record.stderr_tail = run.stderr_excerpt
        record.stdout_log_path = run.stdout_log_path
        record.stderr_log_path = run.stderr_log_path
        record.validation_label = run.label
        record.validator_verdict = validator_record.verdict
        record.validator_reason = validator_record.reason
        record.validator_execution_record = validator_record.execution_record
        record.validator_next_focus = validator_record.next_focus

    def _apply_state_from_outcome(self, outcome: ControllerCycleOutcome, record: AttemptRecord) -> None:
        self.state.current_objective_stage = outcome.objective_stage
        self.state.current_objective = outcome.objective
        self.state.current_controller_reason = outcome.reason
        self.state.validator_memory_file = str(self.config.validator_memory_file)
        self.state.current_branch = self.config.git_branch
        self.state.target_command = self.config.target_command
        if self.state.source_repo_root == "":
            self.state.source_repo_root = str(self.config.project_root)
        if self.state.worktree_root == "":
            self.state.worktree_root = str(self.config.worktree_root)
        logger.info(
            "Controller decision: action=%s stage=%s objective=%s",
            record.controller_action,
            record.objective_stage,
            record.objective_summary,
        )

    def _build_controller_prompt(self, attempt_num: int, head_before: str) -> str:
        return (
            f"Session: {self.state.session_id}\n"
            f"Attempt: {attempt_num} / {self.config.max_attempts}\n"
            f"Target command: {self.config.target_command}\n"
            f"Current worktree branch: {self.config.git_branch}\n"
            f"Current worktree HEAD: {head_before}\n"
            f"Validator memory file: {self.config.validator_memory_file}\n"
            f"Current objective stage: {self.state.current_objective_stage}\n"
            f"Current objective: {self.state.current_objective}\n"
            f"Best successful duration seconds so far: {self._format_duration(self.state.best_success_duration_seconds)}\n\n"
            f"Previous attempts:\n{self.state.format_attempt_history()}\n\n"
            "Drive the next improvement cycle autonomously. "
            "Use validator memory as the durable record of validated state. "
            "If that memory is stale or not synced to the current HEAD, send validator first."
        )

    def _finish_with_status(self, status: str, record: AttemptRecord) -> None:
        self.state.status = status
        self.state.attempts.append(record)
        self.state.save(self.config.state_file)

    def _ensure_runtime_paths(self) -> None:
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        self.config.validator_memory_file.parent.mkdir(parents=True, exist_ok=True)

    def _capture_git_effects(self, record: AttemptRecord) -> None:
        record.head_after = self._rev_parse(self.config.worktree_root, "HEAD")
        record.committed = bool(record.head_before and record.head_after and record.head_after != record.head_before)
        if record.committed:
            record.commit_hash = record.head_after
        record.files_modified = self._collect_modified_files(record.head_before, record.head_after)

    def _collect_modified_files(self, head_before: str, head_after: str) -> list[str]:
        files: set[str] = set()
        if head_before and head_after and head_before != head_after:
            files.update(self._git_lines(self.config.worktree_root, "diff", "--name-only", head_before, head_after))
        files.update(self._git_lines(self.config.worktree_root, "diff", "--name-only"))
        files.update(self._git_lines(self.config.worktree_root, "diff", "--cached", "--name-only"))
        files.update(self._git_lines(self.config.worktree_root, "ls-files", "--others", "--exclude-standard"))
        return sorted(file_name for file_name in files if file_name)

    def _init_source_git_state(self) -> None:
        self.state.original_branch = self._git(self.config.project_root, "branch", "--show-current").strip()
        self.state.current_branch = self.config.git_branch
        self.state.source_head = self._rev_parse(self.config.project_root, "HEAD")
        self.state.source_dirty = bool(self._git(self.config.project_root, "status", "--porcelain").strip())
        if self.state.source_dirty:
            logger.warning(
                "Source repository has uncommitted changes. The isolated worktree is created from HEAD and will not include them."
            )

    def _ensure_isolated_worktree(self) -> None:
        worktree_root = self.config.worktree_root
        if (worktree_root / ".git").exists():
            logger.info("Using existing isolated worktree at %s", worktree_root)
            return
        if worktree_root.exists():
            msg = f"Worktree path exists but is not a git worktree: {worktree_root}"
            raise RuntimeError(msg)

        worktree_root.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = self._git_returncode(
            self.config.project_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{self.config.git_branch}",
        ) == 0
        if branch_exists:
            self._git_checked(
                self.config.project_root,
                "worktree",
                "add",
                str(worktree_root),
                self.config.git_branch,
            )
        else:
            self._git_checked(
                self.config.project_root,
                "worktree",
                "add",
                "-b",
                self.config.git_branch,
                str(worktree_root),
                "HEAD",
            )
        logger.info("Created isolated worktree %s on branch %s", worktree_root, self.config.git_branch)

    def _rollback_to(self, head: str) -> bool:
        if not head:
            return False
        try:
            self._git_checked(self.config.worktree_root, "reset", "--hard", head)
            self._git_checked(self.config.worktree_root, "clean", "-fd")
            return True
        except subprocess.CalledProcessError:
            logger.exception("Rollback failed")
            return False

    def _rev_parse(self, cwd: Path, ref: str) -> str:
        return self._git(cwd, "rev-parse", ref).strip()

    def _git_lines(self, cwd: Path, *args: str) -> list[str]:
        output = self._git(cwd, *args)
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _git(self, cwd: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return completed.stdout

    def _git_checked(self, cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )

    def _git_returncode(self, cwd: Path, *args: str) -> int:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return completed.returncode

    def _update_best_success_duration(self, duration: float | None) -> None:
        if duration is None:
            return
        best = self.state.best_success_duration_seconds
        if best is None or duration < best:
            self.state.best_success_duration_seconds = duration

    @staticmethod
    def _format_duration(duration: float | None) -> str:
        if duration is None:
            return "n/a"
        return f"{duration:.2f}"
