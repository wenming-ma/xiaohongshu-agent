from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable, Protocol

from .agent_runtime import ControllerCycleOutcome, DeepAgentRuntime, RecoveryCycleOutcome, ValidatorRecord
from .config import ClusterConfig
from .state import AttemptRecord, ClusterState, RecoveryRecord

logger = logging.getLogger(__name__)


class _Notifier(Protocol):
    async def send_message(self, text: str, chat_id: str | None = None, parse_mode: str | None = None) -> str | None: ...
    async def send_file(
        self,
        file_path: Path,
        caption: str = "",
        chat_id: str | None = None,
        *,
        duration: int | None = None,
    ) -> str | None: ...
    async def wait_for_reply(self) -> str: ...
    def clear_queue(self) -> None: ...


class Orchestrator:
    def __init__(
        self,
        config: ClusterConfig,
        agent_runtime: DeepAgentRuntime | None = None,
        notifier: _Notifier | None = None,
        restart_callback: Callable[[list[str]], None] | None = None,
    ):
        self.config = config
        self.state = ClusterState(
            session_id=config.session_id,
            target_command=config.target_command,
            source_repo_root=str(config.project_root),
            worktree_root=str(config.worktree_root),
            controller_memory_file=str(config.controller_memory_file),
            validator_memory_file=str(config.validator_memory_file),
        )
        self._agent_runtime = agent_runtime
        self._notifier = notifier
        self._restart_callback = restart_callback

    async def run(self) -> bool:
        consecutive_rollbacks = 0
        attempt_limit = self._attempt_limit()
        bootstrap_complete = False
        attempt_num = len(self.state.attempts) + 1

        while attempt_num <= attempt_limit:
            head_before = ""
            phase = "bootstrap.init_agent_runtime"
            try:
                if self._agent_runtime is None:
                    self._agent_runtime = DeepAgentRuntime(self.config)
                if not bootstrap_complete:
                    phase = "bootstrap.init_source_git_state"
                    self._init_source_git_state()
                    phase = "bootstrap.ensure_isolated_worktree"
                    self._ensure_isolated_worktree()
                    phase = "bootstrap.ensure_runtime_paths"
                    self._ensure_runtime_paths()
                    bootstrap_complete = True

                logger.info("=" * 60)
                logger.info("ATTEMPT #%d / %d", attempt_num, attempt_limit)
                logger.info("=" * 60)

                phase = "attempt.rev_parse_head"
                head_before = self._rev_parse(self.config.worktree_root, "HEAD")
                phase = "attempt.run_controller_cycle"
                outcome = await self._agent_runtime.run_controller_cycle(
                    self._build_controller_prompt(attempt_num, head_before),
                    attempt_number=attempt_num,
                )
                phase = "attempt.record_attempt"
                record = self._record_attempt(attempt_num, head_before, outcome)
                phase = "attempt.capture_git_effects"
                self._capture_git_effects(record)
                phase = "attempt.apply_state"
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
                    self._clear_pending_pull_request()
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
                    completed = await self._handle_done_action(
                        attempt_num=attempt_num,
                        attempt_limit=attempt_limit,
                        record=record,
                    )
                    if completed is True:
                        return True
                    if completed is False:
                        return False
                    attempt_num += 1
                    continue

                self._append_attempt_and_save(record)

                if self.config.sleep_between_attempts > 0:
                    phase = "attempt.sleep"
                    await asyncio.sleep(self.config.sleep_between_attempts)
                attempt_num += 1
            except Exception as exc:
                if not await self._recover_from_exception(
                    exc,
                    phase=phase,
                    attempt_number=attempt_num,
                    head_before=head_before,
                ):
                    return False
                self._restart_process()
                self.state.status = "running"
                continue

        try:
            logger.error("Max attempts (%d) exhausted", attempt_limit)
            self.state.status = "exhausted"
            self._save_state()
            return False
        except Exception as exc:
            if not await self._recover_from_exception(
                exc,
                phase="finalize.exhausted_save",
                attempt_number=attempt_limit,
                head_before="",
            ):
                return False
            self._restart_process()
            self.state.status = "running"
            return await self.run()

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
            controller_memory_path=str(self.config.controller_memory_file),
            validator_memory_path=str(self.config.validator_memory_file),
            workers=outcome.workers,
        )
        if outcome.pull_request_request is not None:
            record.pull_request_requested = True
            record.pull_request_title = outcome.pull_request_request.title
            record.pull_request_body = outcome.pull_request_request.body
            record.pull_request_base_branch = outcome.pull_request_request.base_branch
            record.pull_request_draft = outcome.pull_request_request.draft
        record.output_dir = self._normalize_output_dir(outcome.output_dir)
        record.video_path = self._normalize_video_path(outcome.review_video_path, record.output_dir)
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
        self.state.controller_memory_file = str(self.config.controller_memory_file)
        self.state.validator_memory_file = str(self.config.validator_memory_file)
        self.state.current_branch = self.config.git_branch
        self.state.target_command = self.config.target_command
        if outcome.pull_request_request is not None:
            self.state.pending_pull_request_title = outcome.pull_request_request.title
            self.state.pending_pull_request_body = outcome.pull_request_request.body
            self.state.pending_pull_request_base_branch = outcome.pull_request_request.base_branch
            self.state.pending_pull_request_draft = outcome.pull_request_request.draft
        else:
            self._clear_pending_pull_request()
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
            f"Attempt: {attempt_num} / {self._attempt_limit()}\n"
            f"Target command: {self.config.target_command}\n"
            f"Current worktree branch: {self.config.git_branch}\n"
            f"Current worktree HEAD: {head_before}\n"
            f"Rollback target for this attempt: {head_before}\n"
            f"Minimum attempts before finish is allowed: {self.config.min_attempts_before_finish}\n"
            f"Controller memory file: {self.config.controller_memory_file}\n"
            f"Validator memory file: {self.config.validator_memory_file}\n"
            f"Posts root: {self.config.project_root / 'posts'}\n"
            f"Pull request base branch: {self.config.pull_request_base_branch}\n"
            f"Latest user feedback: {self.state.current_user_feedback or 'none'}\n"
            f"Latest reviewed video path: {self.state.current_review_video_path or 'none'}\n"
            f"Current objective stage: {self.state.current_objective_stage}\n"
            f"Current objective: {self.state.current_objective}\n"
            f"Best successful duration seconds so far: {self._format_duration(self.state.best_success_duration_seconds)}\n\n"
            f"Previous attempts:\n{self.state.format_attempt_history()}\n\n"
            "Drive the next improvement cycle autonomously. "
            "Use validator memory as the durable record of validated state. "
            "If that memory is stale or not synced to the current HEAD, send validator first. "
            "Do not trust validator alone when deciding to stop. Before requesting done, inspect the relevant directory under posts root and confirm the successful published outputs are actually present and materially complete. "
            "If the current branch is review-worthy for main, you may request a pull request. Python will push the branch and create the PR only after legality checks. "
            "If this attempt should be discarded, call the rollback request tool with the rollback target above. "
            "If the current validated state is sufficient to stop, call the done request tool. "
            "If you request done, you must return review_video_path for the completed artifact; Python will reject done requests that omit it. "
            "A done request before the minimum-attempt threshold becomes a progress checkpoint: Python will notify the user via Telegram, send the generated video, collect user feedback, and continue the outer loop. "
            "After the threshold, Python still requires explicit user approval feedback before it will finalize the run."
        )

    def _finish_with_status(self, status: str, record: AttemptRecord) -> None:
        self.state.status = status
        self._append_attempt_and_save(record)

    def _ensure_runtime_paths(self) -> None:
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        self.config.controller_memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.validator_memory_file.parent.mkdir(parents=True, exist_ok=True)

    async def _handle_done_action(
        self,
        *,
        attempt_num: int,
        attempt_limit: int,
        record: AttemptRecord,
    ) -> bool | None:
        if not record.video_path:
            logger.warning("Controller requested done without returning review_video_path; continuing the loop")
            record.controller_reason = (
                (record.controller_reason + " " if record.controller_reason else "")
                + "Done request rejected because controller did not return review_video_path."
            ).strip()
            self._append_attempt_and_save(record)
            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)
            return None
        if not Path(record.video_path).exists():
            logger.warning(
                "Controller requested done with a missing review_video_path %s; continuing the loop",
                record.video_path,
            )
            record.controller_reason = (
                (record.controller_reason + " " if record.controller_reason else "")
                + "Done request rejected because review_video_path does not exist."
            ).strip()
            self._append_attempt_and_save(record)
            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)
            return None
        if not Path(record.video_path).is_file():
            logger.warning(
                "Controller requested done with a non-file review_video_path %s; continuing the loop",
                record.video_path,
            )
            record.controller_reason = (
                (record.controller_reason + " " if record.controller_reason else "")
                + "Done request rejected because review_video_path is not a file."
            ).strip()
            self._append_attempt_and_save(record)
            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)
            return None
        self.state.current_review_video_path = record.video_path
        feedback = await self._handle_done_review(attempt_num, attempt_limit, record)
        if feedback:
            record.user_feedback = feedback
            self.state.current_user_feedback = feedback
            self.state.current_review_video_path = record.video_path
            if hasattr(self._agent_runtime, "note_user_feedback"):
                self._agent_runtime.note_user_feedback(
                    attempt_number=attempt_num,
                    feedback=feedback,
                    video_path=record.video_path,
                    output_dir=record.output_dir,
                )
        if attempt_num < self.config.min_attempts_before_finish:
            logger.info(
                "Controller requested done at attempt #%d, but the loop must run at least %d attempts",
                attempt_num,
                self.config.min_attempts_before_finish,
            )
            self._append_attempt_and_save(record)
            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)
            return None
        if not self._is_feedback_approval(feedback):
            logger.info("User feedback did not approve ending the loop; continuing to the next attempt")
            self._append_attempt_and_save(record)
            if self.config.sleep_between_attempts > 0:
                await asyncio.sleep(self.config.sleep_between_attempts)
            return None
        if record.exit_code == 0:
            self._maybe_create_pull_request(record)
            logger.info("Controller ended the loop with a passing validated state")
            self._finish_with_status("success", record)
            return True
        logger.error("Controller stopped but the latest validated state is not passing")
        self._finish_with_status("stuck", record)
        return False

    def _maybe_create_pull_request(self, record: AttemptRecord) -> None:
        title = record.pull_request_title or self.state.pending_pull_request_title
        body = record.pull_request_body or self.state.pending_pull_request_body
        base_branch = record.pull_request_base_branch or self.state.pending_pull_request_base_branch or self.config.pull_request_base_branch
        draft = record.pull_request_draft or self.state.pending_pull_request_draft

        if not title or not body:
            return
        if self.state.pull_request_url:
            record.pull_request_url = self.state.pull_request_url
            return
        if not self._branch_has_reviewable_changes():
            message = "Pull request request ignored because the CI branch has no reviewable commit delta."
            logger.info(message)
            record.pull_request_error = message
            self.state.pull_request_error = message
            self._clear_pending_pull_request()
            return

        existing_url = self._find_existing_pull_request(base_branch)
        if existing_url:
            logger.info("Using existing pull request for branch %s: %s", self.config.git_branch, existing_url)
            record.pull_request_url = existing_url
            self.state.pull_request_url = existing_url
            self.state.pull_request_error = ""
            self._clear_pending_pull_request()
            return

        try:
            self._git_checked(self.config.worktree_root, "push", "-u", "origin", self.config.git_branch)
            args = [
                "gh",
                "pr",
                "create",
                "--base",
                base_branch,
                "--head",
                self.config.git_branch,
                "--title",
                title,
                "--body",
                body,
            ]
            if draft:
                args.append("--draft")
            completed = subprocess.run(
                args,
                cwd=str(self.config.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            url = self._extract_pr_url(completed.stdout)
            record.pull_request_url = url
            self.state.pull_request_url = url
            self.state.pull_request_error = ""
            self._clear_pending_pull_request()
            logger.info("Created pull request against %s: %s", base_branch, url or "unknown-url")
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or str(exc)).strip()
            logger.exception("Failed to create pull request against %s", base_branch)
            record.pull_request_error = message
            self.state.pull_request_error = message

    def _branch_has_reviewable_changes(self) -> bool:
        source_head = self.state.source_head.strip()
        if not source_head:
            return True
        try:
            current_head = self._rev_parse(self.config.worktree_root, "HEAD")
        except subprocess.CalledProcessError:
            return True
        return bool(current_head and current_head != source_head)

    def _find_existing_pull_request(self, base_branch: str) -> str:
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--head",
                    self.config.git_branch,
                    "--base",
                    base_branch,
                    "--json",
                    "url",
                    "--limit",
                    "1",
                ],
                cwd=str(self.config.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            data = json.loads(completed.stdout or "[]")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                url = str(data[0].get("url", "")).strip()
                return url
        except Exception:
            logger.debug("Could not query existing pull requests for branch %s", self.config.git_branch, exc_info=True)
        return ""

    @staticmethod
    def _extract_pr_url(output: str) -> str:
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate
        return ""

    def _clear_pending_pull_request(self) -> None:
        self.state.pending_pull_request_title = ""
        self.state.pending_pull_request_body = ""
        self.state.pending_pull_request_base_branch = ""
        self.state.pending_pull_request_draft = False

    async def _recover_from_exception(
        self,
        exc: Exception,
        *,
        phase: str,
        attempt_number: int,
        head_before: str,
    ) -> bool:
        recovery_number = self._recovery_count(attempt_number) + 1
        traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        traceback_log_path = self._write_traceback_log(
            attempt_number=attempt_number,
            recovery_number=recovery_number,
            traceback_text=traceback_text,
        )
        logger.exception(
            "Unhandled CI agent exception in phase %s (attempt=%d, recovery=%d)",
            phase,
            attempt_number,
            recovery_number,
        )

        record = RecoveryRecord(
            attempt_number=attempt_number,
            recovery_number=recovery_number,
            phase=phase,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_excerpt=self._clip(traceback_text, 4000),
            traceback_log_path=str(traceback_log_path),
            head_before=head_before,
            status="captured",
        )

        if recovery_number > self.config.max_recovery_attempts_per_attempt:
            logger.error(
                "Max recovery attempts (%d) reached for attempt %d",
                self.config.max_recovery_attempts_per_attempt,
                attempt_number,
            )
            record.status = "limit_exceeded"
            record.reason = "Too many recovery cycles for the same attempt."
            self._append_recovery_record(record)
            self.state.status = "stuck"
            self._save_state()
            return False

        if head_before and self.config.worktree_root.exists():
            if not self._rollback_to(head_before):
                record.status = "rollback_failed"
                record.reason = f"Could not reset isolated worktree to {head_before} before recovery."
                self._append_recovery_record(record)
                self.state.status = "stuck"
                self._save_state()
                return False

        self.state.status = "recovering"
        self._append_recovery_record(record)
        self._save_state()

        try:
            if self._agent_runtime is None:
                self._agent_runtime = DeepAgentRuntime(self.config)
            outcome = await self._agent_runtime.run_recovery_cycle(
                self._build_recovery_prompt(
                    attempt_number=attempt_number,
                    recovery_number=recovery_number,
                    phase=phase,
                    head_before=head_before,
                    traceback_log_path=traceback_log_path,
                    traceback_text=traceback_text,
                ),
                attempt_number=attempt_number,
            )
        except Exception as recovery_exc:
            logger.exception("Recovery agent failed while handling phase %s", phase)
            record.status = "recovery_crashed"
            record.reason = str(recovery_exc)
            self.state.recovery_history[-1] = record
            self.state.status = "stuck"
            self._save_state()
            return False

        self._apply_recovery_outcome(record, outcome)
        self.state.recovery_history[-1] = record
        self._save_state()

        if outcome.status != "RECOVERED":
            self.state.status = "stuck"
            self._save_state()
            return False
        logger.info(
            "Recovery #%d for attempt %d succeeded; restarting the CI agent from %s",
            recovery_number,
            attempt_number,
            self.config.state_file,
        )
        return True

    def _apply_recovery_outcome(self, record: RecoveryRecord, outcome: RecoveryCycleOutcome) -> None:
        record.status = outcome.status
        record.reason = outcome.reason
        record.fix_summary = outcome.fix_summary
        record.validation_notes = outcome.validation_notes
        record.restarted = outcome.status == "RECOVERED"

    def _append_recovery_record(self, record: RecoveryRecord) -> None:
        self.state.recovery_history.append(record)

    def _recovery_count(self, attempt_number: int) -> int:
        return sum(1 for record in self.state.recovery_history if record.attempt_number == attempt_number)

    def _write_traceback_log(self, *, attempt_number: int, recovery_number: int, traceback_text: str) -> Path:
        self._ensure_runtime_paths()
        label = "bootstrap" if attempt_number <= 0 else f"attempt-{attempt_number:04d}"
        attempt_dir = self.config.log_dir / label
        attempt_dir.mkdir(parents=True, exist_ok=True)
        path = attempt_dir / f"recovery-{recovery_number:02d}.traceback.log"
        path.write_text(traceback_text, encoding="utf-8")
        return path

    def _build_recovery_prompt(
        self,
        *,
        attempt_number: int,
        recovery_number: int,
        phase: str,
        head_before: str,
        traceback_log_path: Path,
        traceback_text: str,
    ) -> str:
        return (
            f"Session: {self.state.session_id}\n"
            f"Attempt number: {attempt_number}\n"
            f"Recovery number for this attempt: {recovery_number}\n"
            f"Failure phase: {phase}\n"
            f"Source repo root: {self.config.project_root}\n"
            f"Isolated worktree root: {self.config.worktree_root}\n"
            f"State file: {self.config.state_file}\n"
            f"Target command: {self.config.target_command}\n"
            f"Current branch: {self.config.git_branch}\n"
            f"head_before for the failed attempt: {head_before or 'unknown'}\n"
            f"Traceback log path: {traceback_log_path}\n"
            f"Controller memory file: {self.config.controller_memory_file}\n"
            f"Validator memory file: {self.config.validator_memory_file}\n\n"
            f"Previous attempts:\n{self.state.format_attempt_history()}\n\n"
            "You are repairing a CI orchestrator/runtime failure so the process can restart and retry the same attempt number. "
            "Python has already captured the exception. If a worktree head was available, Python reset the isolated worktree back to head_before before invoking you. "
            "Fix the root cause with the smallest coherent change, run focused checks if needed, and return RECOVERED only if the next process run should advance past this failure.\n\n"
            f"Captured traceback:\n{traceback_text}"
        )

    def _append_attempt_and_save(self, record: AttemptRecord) -> None:
        self.state.attempts.append(record)
        try:
            self._save_state()
        except Exception:
            self.state.attempts.pop()
            raise

    def _save_state(self) -> None:
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state.save(self.config.state_file)

    def _restart_process(self) -> None:
        argv = [
            sys.executable,
            str(Path(__file__).with_name("main.py")),
            "--resume",
            str(self.config.state_file),
            "--max-attempts",
            str(self.config.max_attempts),
            "--model",
            self.config.model,
            "--worker-model",
            self.config.worker_model,
            "--target",
            self.config.target_command,
            "--timeout",
            str(self.config.target_timeout),
            "--sleep",
            str(self.config.sleep_between_attempts),
            "--branch",
            self.config.git_branch,
        ]
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
            argv.append("--verbose")
        if self._restart_callback is not None:
            self._restart_callback(argv)
            return
        os.execv(sys.executable, argv)

    def _attempt_limit(self) -> int:
        return max(self.config.max_attempts, self.config.min_attempts_before_finish)

    async def _notify_done_request(self, attempt_num: int, attempt_limit: int, record: AttemptRecord) -> None:
        notifier = self._get_notifier()
        if notifier is None:
            logger.warning("Telegram notifier is unavailable; skipping done-request notification")
            return
        message = self._format_done_request_message(attempt_num, attempt_limit, record)
        try:
            await notifier.send_message(message)
        except Exception:
            logger.exception("Failed to send Telegram notification for controller done request")

    async def _handle_done_review(self, attempt_num: int, attempt_limit: int, record: AttemptRecord) -> str:
        await self._notify_done_request(attempt_num, attempt_limit, record)
        notifier = self._get_notifier()
        if notifier is None:
            return ""
        if hasattr(notifier, "clear_queue"):
            notifier.clear_queue()
        if record.video_path:
            try:
                await notifier.send_file(
                    Path(record.video_path),
                    caption="本轮生成的视频已附上，请检查内容、字幕、中文配音和整体完成度。",
                )
            except Exception:
                logger.exception("Failed to send generated video to Telegram")
        else:
            try:
                await notifier.send_message("未自动发现本轮生成视频文件，请根据输出目录人工检查。")
            except Exception:
                logger.exception("Failed to send missing-video notice to Telegram")
        prompt = (
            "请回复你的反馈。\n"
            "- 如果还需要修改，请直接回复修改意见。\n"
            "- 如果你认可当前结果并允许结束，请回复 APPROVED。"
        )
        try:
            await notifier.send_message(prompt)
            feedback = await notifier.wait_for_reply()
            return feedback.strip()
        except Exception:
            logger.exception("Failed to collect Telegram feedback after done request")
            return ""

    def _get_notifier(self) -> _Notifier | None:
        if self._notifier is not None:
            return self._notifier
        try:
            from src.utils.telegram_notifier import get_telegram_notifier
        except Exception:
            logger.exception("Could not import Telegram notifier")
            return None
        self._notifier = get_telegram_notifier()
        return self._notifier

    def _format_done_request_message(self, attempt_num: int, attempt_limit: int, record: AttemptRecord) -> str:
        finish_allowed = attempt_num >= self.config.min_attempts_before_finish
        status = "等待你的 APPROVED 才会结束" if finish_allowed else f"继续迭代，至少跑到第 {self.config.min_attempts_before_finish} 轮"
        files_line = ", ".join(record.files_modified[:8]) if record.files_modified else "none"
        if len(record.files_modified) > 8:
            files_line += f" ... (+{len(record.files_modified) - 8} more)"
        return (
            "[CI Agent] Controller 请求结束\n"
            f"Session: {self.state.session_id}\n"
            f"Attempt: {attempt_num}/{attempt_limit}\n"
            f"当前处理: {status}\n"
            f"阶段: {record.objective_stage}\n"
            f"目标: {self._clip(record.objective_summary, 180)}\n"
            f"Controller 判断: {self._clip(record.controller_reason, 220)}\n"
            f"本轮优化: {self._clip(record.fix_description or 'No code change summary provided.', 260)}\n"
            f"验证结果: {record.validator_verdict} | exit={record.exit_code} | {self._format_duration(record.duration_seconds)}s\n"
            f"验证说明: {self._clip(record.validator_reason, 220)}\n"
            f"建议下一步: {self._clip(record.validator_next_focus or 'n/a', 180)}\n"
            f"修改文件: {files_line}\n"
            f"Commit: {record.commit_hash or 'none'}\n"
            f"PR 请求: {(record.pull_request_base_branch or 'none') if record.pull_request_requested else 'none'}\n"
            f"PR 链接: {record.pull_request_url or self.state.pull_request_url or 'none'}\n"
            f"输出目录: {record.output_dir or 'unknown'}\n"
            f"视频文件: {record.video_path or 'unknown'}\n"
            f"Worktree branch: {self.config.git_branch}"
        )

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

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(limit - 3, 0)].rstrip() + "..."

    @staticmethod
    def _is_feedback_approval(feedback: str) -> bool:
        return feedback.strip().upper() == "APPROVED"

    def _normalize_output_dir(self, output_dir: str) -> str:
        raw = output_dir.strip()
        if not raw:
            return ""
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.config.worktree_root / path
        return str(path.resolve(strict=False))

    def _normalize_video_path(self, video_path: str, output_dir: str) -> str:
        raw = video_path.strip()
        if not raw:
            return ""
        path = Path(raw).expanduser()
        if not path.is_absolute():
            base_dir = Path(output_dir) if output_dir else self.config.worktree_root
            path = base_dir / path
        return str(path.resolve(strict=False))
