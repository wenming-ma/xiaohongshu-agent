from __future__ import annotations

import asyncio
import logging
import subprocess
from time import perf_counter
from pathlib import Path

from .agent_runtime import ControllerOutcome, DeepAgentRuntime, ValidationOutcome
from .config import ClusterConfig
from .state import AttemptRecord, ClusterState, WorkerInvocation

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

            exit_code, stdout, stderr, duration = self._run_target()
            record.exit_code = exit_code
            record.duration_seconds = duration
            record.stdout_tail = stdout[-TAIL_CHARS:]
            record.stderr_tail = stderr[-TAIL_CHARS:]
            if exit_code == 0:
                self._update_best_success_duration(duration)

            controller = await self._run_controller(attempt_num, record)
            self._apply_controller_decision(record, controller)

            if exit_code == 0 and record.objective_stage == "DONE":
                logger.info("SUCCESS on attempt #%d", attempt_num)
                self._finish_with_status("success", record)
                return True

            if exit_code == 0:
                logger.info(
                    "Target command already passes; pursuing %s objective next",
                    record.objective_stage,
                )
            else:
                logger.warning("Script failed with exit code %d", exit_code)

            history = self.state.format_attempt_history()
            fixer_prompt = self._build_fixer_prompt(record, history)
            logger.info("Running fixer agent...")
            fixer_worker = await self._agent_runtime.run_fixer(
                fixer_prompt,
                system_overlay=record.fixer_directive,
            )
            record.fix_description = fixer_worker.final_text
            record.workers.append(fixer_worker)
            self._capture_git_effects(record)

            logger.info("Running validation target...")
            exit_code_2, stdout_2, stderr_2, duration_2 = self._run_target()
            record.validation_exit_code = exit_code_2
            record.validation_duration_seconds = duration_2
            record.validation_stdout_tail = stdout_2[-TAIL_CHARS:]
            record.validation_stderr_tail = stderr_2[-TAIL_CHARS:]

            if exit_code_2 == 0:
                self._update_best_success_duration(duration_2)
                if record.objective_stage == "PASS":
                    logger.info("Target command now passes; controller can choose higher-order work next")
                    record.validator_verdict = "PROGRESS"
                    record.validator_reason = "The target command passed after the fix."
                    if attempt_num >= self.config.max_attempts:
                        self._finish_with_status("success", record)
                        return True
                    consecutive_rollbacks = 0
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    if self.config.sleep_between_attempts > 0:
                        await asyncio.sleep(self.config.sleep_between_attempts)
                    continue

            if exit_code_2 != 0 and record.objective_stage in {"SPEED", "QUALITY"}:
                validation = ValidationOutcome(
                    verdict="SAME_ERROR",
                    reason=f"{record.objective_stage} optimization broke the target command.",
                    worker=self._synthetic_worker(
                        worker_type="validator",
                        prompt_summary="Automatic rollback because a higher-order optimization regressed the target command.",
                        final_text=f"{record.objective_stage} changes regressed the green baseline.",
                    ),
                )
            else:
                validator_prompt = self._build_validator_prompt(record)
                logger.info("Running validator agent...")
                validation = await self._agent_runtime.run_validator(
                    validator_prompt,
                    system_overlay=record.validator_directive,
                )
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
                if exit_code_2 == 0 and attempt_num >= self.config.max_attempts:
                    self._finish_with_status("success", record)
                    return True

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

    async def _run_controller(self, attempt_num: int, record: AttemptRecord) -> ControllerOutcome:
        logger.info("Running controller agent...")
        prompt = (
            f"Attempt number: {attempt_num} / {self.config.max_attempts}\n"
            f"Current controller stage: {self.state.current_objective_stage}\n"
            f"Current controller objective: {self.state.current_objective}\n"
            f"Latest target exit code: {record.exit_code}\n"
            f"Latest target duration seconds: {self._format_duration(record.duration_seconds)}\n"
            f"Best successful duration seconds so far: {self._format_duration(self.state.best_success_duration_seconds)}\n\n"
            f"=== STDOUT (tail) ===\n{record.stdout_tail}\n\n"
            f"=== STDERR (tail) ===\n{record.stderr_tail}\n\n"
            f"=== Previous attempts ===\n{self.state.format_attempt_history()}\n\n"
            "Choose the single next objective stage and describe the concrete objective for one fixer attempt."
        )
        return await self._agent_runtime.run_controller(prompt)

    def _apply_controller_decision(self, record: AttemptRecord, controller: ControllerOutcome) -> None:
        stage = controller.stage
        objective = controller.objective.strip() or "Make the target command pass."
        reason = controller.reason.strip()

        if record.exit_code != 0 and stage != "PASS":
            logger.info("Overriding controller stage %s to PASS because the target command is failing", stage)
            stage = "PASS"
            objective = "Make the target command pass before attempting speed or quality work."
            reason = (
                f"Controller requested {controller.stage}, but the latest target run failed, so the stage was forced to PASS."
            )

        record.objective_stage = stage
        record.objective_summary = objective
        record.controller_reason = reason
        record.fixer_directive = controller.fixer_system_overlay.strip()
        record.validator_directive = controller.validator_system_overlay.strip()
        controller.worker.final_text = f"{objective}\nReason: {reason}".strip()
        record.workers.append(controller.worker)
        self.state.current_objective_stage = stage
        self.state.current_objective = objective
        self.state.current_controller_reason = reason
        self.state.current_fixer_directive = record.fixer_directive
        self.state.current_validator_directive = record.validator_directive

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

    def _build_fixer_prompt(self, record: AttemptRecord, history: str) -> str:
        baseline_status = "passed" if record.exit_code == 0 else f"failed with exit code {record.exit_code}"
        return (
            f"The latest target command {baseline_status}.\n"
            f"Current objective stage: {record.objective_stage}\n"
            f"Current objective: {record.objective_summary}\n"
            f"Best successful duration so far: {self._format_duration(self.state.best_success_duration_seconds)}\n\n"
            f"=== STDOUT (tail) ===\n{record.stdout_tail}\n\n"
            f"=== STDERR (tail) ===\n{record.stderr_tail}\n\n"
            f"=== Previous attempts (DO NOT repeat failed fixes) ===\n{history}\n\n"
            f"=== Git branch ===\n{self.config.git_branch}\n\n"
            "Make one coherent change set that advances the current objective without regressing the target command."
        )

    def _build_validator_prompt(self, record: AttemptRecord) -> str:
        return (
            f"Objective stage: {record.objective_stage}\n"
            f"Objective: {record.objective_summary}\n"
            f"Target duration before fix: {self._format_duration(record.duration_seconds)}\n"
            f"Target duration after fix: {self._format_duration(record.validation_duration_seconds)}\n"
            f"Files modified: {', '.join(record.files_modified) or 'none'}\n\n"
            f"=== STDERR BEFORE FIX ===\n{record.stderr_tail}\n\n"
            f"=== STDERR AFTER FIX ===\n{record.validation_stderr_tail}\n\n"
            f"=== FIX SUMMARY ===\n{record.fix_description[:1000]}\n\n"
            "Decide whether this attempt made meaningful progress toward the stated objective."
        )

    def _synthetic_worker(self, worker_type: str, prompt_summary: str, final_text: str):
        return WorkerInvocation(
            worker_type=worker_type,
            prompt_summary=prompt_summary,
            final_text=final_text,
        )

    def _run_target(self) -> tuple[int, str, str, float]:
        logger.info("Running in %s: %s", self.config.worktree_root, self.config.target_command)
        started = perf_counter()
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
            return result.returncode, result.stdout or "", result.stderr or "", perf_counter() - started
        except subprocess.TimeoutExpired:
            return -1, "", f"TIMEOUT after {self.config.target_timeout}s", perf_counter() - started
        except Exception as exc:
            return -1, "", str(exc), perf_counter() - started

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
