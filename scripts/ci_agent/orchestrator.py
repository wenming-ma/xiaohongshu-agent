from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Protocol

from .agent_runtime import ControllerCycleOutcome, DeepAgentRuntime, ValidatorRecord
from .config import ClusterConfig
from .state import AttemptRecord, ClusterState

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

    async def run(self) -> bool:
        self._init_source_git_state()
        self._ensure_isolated_worktree()
        self._ensure_runtime_paths()

        if self._agent_runtime is None:
            self._agent_runtime = DeepAgentRuntime(self.config)

        consecutive_rollbacks = 0
        start_attempt = len(self.state.attempts) + 1

        attempt_limit = self._attempt_limit()

        for attempt_num in range(start_attempt, attempt_limit + 1):
            logger.info("=" * 60)
            logger.info("ATTEMPT #%d / %d", attempt_num, attempt_limit)
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
                if not record.video_path:
                    logger.warning("Controller requested done without returning review_video_path; continuing the loop")
                    record.controller_reason = (
                        (record.controller_reason + " " if record.controller_reason else "")
                        + "Done request rejected because controller did not return review_video_path."
                    ).strip()
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    if self.config.sleep_between_attempts > 0:
                        await asyncio.sleep(self.config.sleep_between_attempts)
                    continue
                if not Path(record.video_path).exists():
                    logger.warning(
                        "Controller requested done with a missing review_video_path %s; continuing the loop",
                        record.video_path,
                    )
                    record.controller_reason = (
                        (record.controller_reason + " " if record.controller_reason else "")
                        + "Done request rejected because review_video_path does not exist."
                    ).strip()
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    if self.config.sleep_between_attempts > 0:
                        await asyncio.sleep(self.config.sleep_between_attempts)
                    continue
                if not Path(record.video_path).is_file():
                    logger.warning(
                        "Controller requested done with a non-file review_video_path %s; continuing the loop",
                        record.video_path,
                    )
                    record.controller_reason = (
                        (record.controller_reason + " " if record.controller_reason else "")
                        + "Done request rejected because review_video_path is not a file."
                    ).strip()
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    if self.config.sleep_between_attempts > 0:
                        await asyncio.sleep(self.config.sleep_between_attempts)
                    continue
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
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    if self.config.sleep_between_attempts > 0:
                        await asyncio.sleep(self.config.sleep_between_attempts)
                    continue
                if not self._is_feedback_approval(feedback):
                    logger.info("User feedback did not approve ending the loop; continuing to the next attempt")
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    if self.config.sleep_between_attempts > 0:
                        await asyncio.sleep(self.config.sleep_between_attempts)
                    continue
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

        logger.error("Max attempts (%d) exhausted", attempt_limit)
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
            controller_memory_path=str(self.config.controller_memory_file),
            validator_memory_path=str(self.config.validator_memory_file),
            workers=outcome.workers,
        )
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
            f"Latest user feedback: {self.state.current_user_feedback or 'none'}\n"
            f"Latest reviewed video path: {self.state.current_review_video_path or 'none'}\n"
            f"Current objective stage: {self.state.current_objective_stage}\n"
            f"Current objective: {self.state.current_objective}\n"
            f"Best successful duration seconds so far: {self._format_duration(self.state.best_success_duration_seconds)}\n\n"
            f"Previous attempts:\n{self.state.format_attempt_history()}\n\n"
            "Drive the next improvement cycle autonomously. "
            "Use validator memory as the durable record of validated state. "
            "If that memory is stale or not synced to the current HEAD, send validator first. "
            "If this attempt should be discarded, call the rollback request tool with the rollback target above. "
            "If the current validated state is sufficient to stop, call the done request tool. "
            "If you request done, you must return review_video_path for the completed artifact; Python will reject done requests that omit it. "
            "A done request before the minimum-attempt threshold becomes a progress checkpoint: Python will notify the user via Telegram, send the generated video, collect user feedback, and continue the outer loop. "
            "After the threshold, Python still requires explicit user approval feedback before it will finalize the run."
        )

    def _finish_with_status(self, status: str, record: AttemptRecord) -> None:
        self.state.status = status
        self.state.attempts.append(record)
        self.state.save(self.config.state_file)

    def _ensure_runtime_paths(self) -> None:
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        self.config.controller_memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.validator_memory_file.parent.mkdir(parents=True, exist_ok=True)

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
