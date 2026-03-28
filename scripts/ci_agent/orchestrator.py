from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from .agent_runtime import DeepAgentRuntime, ValidationOutcome
from .config import ClusterConfig
from .state import AttemptRecord, ClusterState

logger = logging.getLogger(__name__)

TAIL_CHARS = 4000


class Orchestrator:
    def __init__(self, config: ClusterConfig, agent_runtime: DeepAgentRuntime | None = None):
        self.config = config
        self.state = ClusterState(
            session_id=config.session_id,
            target_command=config.target_command,
            source_repo_root=str(config.project_root),
            worktree_root=str(config.worktree_root),
        )
        self._agent_runtime = agent_runtime

    async def run(self) -> bool:
        self._init_source_git_state()
        self._ensure_isolated_worktree()

        if self._agent_runtime is None:
            self._agent_runtime = DeepAgentRuntime(self.config)

        consecutive_rollbacks = 0

        for attempt_num in range(1, self.config.max_attempts + 1):
            logger.info("=" * 60)
            logger.info("ATTEMPT #%d / %d", attempt_num, self.config.max_attempts)
            logger.info("=" * 60)

            record = AttemptRecord(
                attempt_number=attempt_num,
                head_before=self._rev_parse(self.config.worktree_root, "HEAD"),
            )

            exit_code, stdout, stderr = self._run_target()
            record.exit_code = exit_code
            record.stdout_tail = stdout[-TAIL_CHARS:]
            record.stderr_tail = stderr[-TAIL_CHARS:]

            if exit_code == 0:
                logger.info("SUCCESS on attempt #%d", attempt_num)
                self._finish_with_status("success", record)
                return True

            logger.warning("Script failed with exit code %d", exit_code)

            history = self.state.format_attempt_history()
            fixer_prompt = (
                f"The script failed with exit code {exit_code}.\n\n"
                f"=== STDOUT (tail) ===\n{record.stdout_tail}\n\n"
                f"=== STDERR (tail) ===\n{record.stderr_tail}\n\n"
                f"=== Previous attempts (DO NOT repeat failed fixes) ===\n{history}\n\n"
                f"=== Git branch ===\n{self.config.git_branch}\n\n"
                "Analyze the error, make the smallest fix you can justify, and commit it if the fix is coherent enough to keep."
            )
            logger.info("Running fixer agent...")
            fixer_worker = await self._agent_runtime.run_fixer(fixer_prompt)
            record.fix_description = fixer_worker.final_text
            record.workers.append(fixer_worker)
            self._capture_git_effects(record)

            logger.info("Running validation target...")
            exit_code_2, stdout_2, stderr_2 = self._run_target()
            record.validation_exit_code = exit_code_2
            record.validation_stdout_tail = stdout_2[-TAIL_CHARS:]
            record.validation_stderr_tail = stderr_2[-TAIL_CHARS:]

            if exit_code_2 == 0:
                logger.info("SUCCESS after fix on attempt #%d", attempt_num)
                self._finish_with_status("success", record)
                return True

            validator_prompt = (
                f"=== STDERR BEFORE FIX ===\n{record.stderr_tail}\n\n"
                f"=== STDERR AFTER FIX ===\n{record.validation_stderr_tail}\n\n"
                f"=== FIX SUMMARY ===\n{record.fix_description[:1000]}\n\n"
                "Decide whether the fix changed the failure meaningfully."
            )
            logger.info("Running validator agent...")
            validation = await self._agent_runtime.run_validator(validator_prompt)
            self._record_validation(record, validation)
            logger.info("Verdict: %s", validation.verdict)

            if validation.verdict == "SAME_ERROR":
                logger.warning("Validator says SAME_ERROR; discarding worktree changes")
                if not self._rollback_to(record.head_before):
                    logger.error("Could not roll back isolated worktree to %s", record.head_before)
                    self._finish_with_status("stuck", record)
                    return False
                record.rolled_back = True
                record.rollback_to = record.head_before
                consecutive_rollbacks += 1
                if consecutive_rollbacks >= self.config.max_consecutive_rollbacks:
                    logger.error(
                        "Max consecutive rollbacks (%d) reached",
                        self.config.max_consecutive_rollbacks,
                    )
                    self._finish_with_status("stuck", record)
                    return False
            else:
                consecutive_rollbacks = 0

            self.state.attempts.append(record)
            self.state.save(self.config.state_file)

            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)

        logger.error("Max attempts (%d) exhausted", self.config.max_attempts)
        self.state.status = "exhausted"
        self.state.save(self.config.state_file)
        return False

    def _finish_with_status(self, status: str, record: AttemptRecord) -> None:
        self.state.status = status
        self.state.attempts.append(record)
        self.state.save(self.config.state_file)

    def _record_validation(self, record: AttemptRecord, validation: ValidationOutcome) -> None:
        record.validator_verdict = validation.verdict
        record.validator_reason = validation.reason
        record.workers.append(validation.worker)

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

    def _run_target(self) -> tuple[int, str, str]:
        logger.info("Running in %s: %s", self.config.worktree_root, self.config.target_command)
        try:
            result = subprocess.run(
                self.config.target_command,
                shell=True,
                cwd=str(self.config.worktree_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.target_timeout,
                env=self.config.build_env(),
            )
            return result.returncode, result.stdout or "", result.stderr or ""
        except subprocess.TimeoutExpired:
            return -1, "", f"TIMEOUT after {self.config.target_timeout}s"
        except Exception as exc:
            return -1, "", str(exc)

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
