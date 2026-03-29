import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.ci_agent.agent_runtime import (
    ControllerMemoryStore,
    ControllerCycleOutcome,
    DoneRequest,
    PullRequestRequest,
    RecoveryCycleOutcome,
    RollbackRequest,
    ValidationCommandRunner,
    ValidationRunReport,
    ValidatorRecord,
    _extract_model_output_text,
    _extract_stream_result,
    _log_stream_event,
    _resolve_cycle_action,
)
from scripts.ci_agent.config import ClusterConfig
from scripts.ci_agent.orchestrator import Orchestrator
from scripts.ci_agent.state import ClusterState, WorkerInvocation


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def _create_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "ci-agent@example.com")
    _git(repo, "config", "user.name", "CI Agent")
    (repo / "app.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "init")
    return repo


def _validation_report(
    config: ClusterConfig,
    *,
    attempt_number: int,
    label: str,
    exit_code: int,
    duration_seconds: float,
    stdout: str,
    stderr: str,
) -> ValidationRunReport:
    attempt_dir = config.log_dir / f"attempt-{attempt_number:04d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = attempt_dir / f"{label}.stdout.log"
    stderr_path = attempt_dir / f"{label}.stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    return ValidationRunReport(
        label=label,
        exit_code=exit_code,
        duration_seconds=duration_seconds,
        started_at=now,
        ended_at=now,
        stdout_excerpt=stdout[-4000:],
        stderr_excerpt=stderr[-4000:],
        stdout_log_path=str(stdout_path),
        stderr_log_path=str(stderr_path),
    )


def _validator_record(
    config: ClusterConfig,
    *,
    attempt_number: int,
    label: str,
    exit_code: int,
    duration_seconds: float,
    stdout: str,
    stderr: str,
    verdict: str,
    reason: str,
    execution_record: str,
    next_focus: str = "",
) -> ValidatorRecord:
    return ValidatorRecord(
        verdict=verdict,
        reason=reason,
        execution_record=execution_record,
        next_focus=next_focus,
        latest_validation=_validation_report(
            config,
            attempt_number=attempt_number,
            label=label,
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            stdout=stdout,
            stderr=stderr,
        ),
    )


def test_cluster_config_defaults_to_session_scoped_cache_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=repo / ".cache" / "ci_agent",
        session_id="session123",
    )

    assert config.model == "openai:gpt-5.4"
    assert config.controller_max_retries == 20
    assert config.controller_timeout_seconds == 300
    assert config.worker_model == "MiniMax-M2.7"
    assert config.worker_base_url == "https://api.minimaxi.com/v1"
    assert config.pull_request_base_branch == "main"
    assert config.min_attempts_before_finish == 10
    assert config.state_file == repo / ".cache" / "ci_agent" / "sessions" / "session123" / "state.json"
    assert config.log_dir == repo / ".cache" / "ci_agent" / "logs" / "session123"
    assert config.worktree_root == repo / ".cache" / "ci_agent" / "worktrees" / "session123"
    assert config.controller_memory_file == repo / ".cache" / "ci_agent" / "memory" / "session123" / "controller.md"
    assert config.validator_memory_file == repo / ".cache" / "ci_agent" / "memory" / "session123" / "validator.md"
    assert config.git_branch == "ci-agent/session123"
    built_env = config.build_env()
    assert built_env["PYTHONUTF8"] == "1"
    assert built_env["PYTHONIOENCODING"] == "utf-8"
    assert built_env["CI_AGENT_POSTS_ROOT"] == str(repo / "posts")


def test_controller_prompt_requires_posts_verification_before_done(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
    )
    orchestrator = Orchestrator(config, agent_runtime=object())  # type: ignore[arg-type]
    prompt = orchestrator._build_controller_prompt(attempt_num=1, head_before="abc123")

    assert f"Posts root: {repo / 'posts'}" in prompt
    assert "Do not trust validator alone when deciding to stop." in prompt
    assert "confirm the successful published outputs are actually present and materially complete" in prompt


def test_build_controller_model_uses_chat_completions_settings(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(
        "OPENAI_API_KEY=test-openai-key\n"
        "OPENAI_BASE_URL=https://sub2api.wenming-dev.org/v1\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=repo / ".cache" / "ci_agent",
        session_id="session123",
    )

    model = config.build_controller_model()

    assert model.model_name == "gpt-5.4"
    assert str(model.openai_api_base) == "https://sub2api.wenming-dev.org/v1"
    assert model.use_responses_api is False
    assert model.output_version == "v0"
    assert model.max_retries == 20


def test_cluster_config_prefers_minimax_openai_base_url(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(
        "MINIMAX_ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic\n"
        "MINIMAX_OPENAI_BASE_URL=https://api.minimaxi.com/v1\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIMAX_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MINIMAX_ANTHROPIC_BASE_URL", raising=False)

    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=repo / ".cache" / "ci_agent",
        session_id="session123",
    )

    assert config.worker_base_url == "https://api.minimaxi.com/v1"


def test_worktree_is_created_without_moving_main_branch(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
    )

    orchestrator = Orchestrator(config, agent_runtime=object())  # type: ignore[arg-type]
    orchestrator._init_source_git_state()
    orchestrator._ensure_isolated_worktree()

    assert _git(repo, "branch", "--show-current") == "main"
    assert config.worktree_root.exists()
    assert _git(config.worktree_root, "branch", "--show-current") == "ci-agent/session123"


def test_validation_command_runner_writes_logs_and_duration(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=repo / ".cache" / "ci_agent",
        session_id="session123",
        worktree_root=repo,
        target_command='python -c "import sys; print(\'ok\'); print(\'err\', file=sys.stderr)"',
    )
    runner = ValidationCommandRunner(config)

    report = runner.run(attempt_number=1, label="smoke")

    assert report.exit_code == 0
    assert "ok" in report.stdout
    assert "err" in report.stderr
    assert report.duration_seconds >= 0
    assert Path(report.stdout_log_path).exists()
    assert Path(report.stderr_log_path).exists()
    assert Path(report.stdout_log_path).read_text(encoding="utf-8") == report.stdout
    assert Path(report.stderr_log_path).read_text(encoding="utf-8") == report.stderr


def test_controller_memory_store_keeps_notes_short_and_marks_rollbacks(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    store = ControllerMemoryStore(tmp_path / "controller.md", repo)
    store.ensure_exists()

    long_text = "alpha " * 200
    path = store.record_strategy(
        attempt_number=1,
        objective_stage="PASS",
        objective="Make the target command pass.",
        summary=long_text,
        next_focus=long_text,
        discarded_options=long_text,
        evidence=long_text,
    )

    text = Path(path).read_text(encoding="utf-8")
    assert "# Controller Memory" in text
    assert "Attempt: 1" in text
    assert len(text) < 3000

    store.note_rollback(attempt_number=1, rollback_to="abc123", reason="same root cause")
    rolled_back = Path(path).read_text(encoding="utf-8")
    assert "needs re-evaluation" in rolled_back
    assert "Rollback After Attempt 1" in rolled_back


def test_rollback_action_requires_explicit_request() -> None:
    assert _resolve_cycle_action(None, None) == "CONTINUE"
    assert _resolve_cycle_action(None, DoneRequest(reason="good enough")) == "DONE"
    assert _resolve_cycle_action(RollbackRequest(head="abc123", reason="discard"), None) == "ROLLBACK"
    assert (
        _resolve_cycle_action(
            RollbackRequest(head="abc123", reason="discard"),
            DoneRequest(reason="good enough"),
        )
        == "ROLLBACK"
    )


def test_stream_event_logging_reports_controller_delegation(caplog) -> None:
    run_names: dict[str, str] = {}
    event = {
        "event": "on_tool_start",
        "name": "task",
        "run_id": "run-task",
        "parent_ids": [],
        "data": {"input": {"subagent_type": "validator"}},
    }

    with caplog.at_level(logging.INFO):
        _log_stream_event(event, run_names)

    assert "delegating to validator" in caplog.text


def test_stream_event_logging_normalizes_general_purpose_to_task(caplog) -> None:
    run_names: dict[str, str] = {}
    event = {
        "event": "on_tool_start",
        "name": "task",
        "run_id": "run-task",
        "parent_ids": [],
        "data": {"input": {"subagent_type": "general-purpose"}},
    }

    with caplog.at_level(logging.INFO):
        _log_stream_event(event, run_names)

    assert "delegating to task" in caplog.text


def test_stream_event_logging_inferrs_agent_from_parent_chain(caplog) -> None:
    run_names = {"validator-run": "ci-agent-validator"}
    event = {
        "event": "on_tool_start",
        "name": "run_validation_command",
        "run_id": "tool-run",
        "parent_ids": ["validator-run"],
        "data": {"input": {"label": "post-fix-validation"}},
    }

    with caplog.at_level(logging.INFO):
        _log_stream_event(event, run_names)

    assert "[validator] tool start: run_validation_command | post-fix-validation" in caplog.text


def test_extract_stream_result_reads_root_chain_output() -> None:
    output = {"messages": ["done"]}
    event = {
        "event": "on_chain_end",
        "name": "ci-agent-controller",
        "data": {"output": output},
    }

    assert _extract_stream_result(event, "ci-agent-controller") == output


def test_extract_model_output_prefers_thinking_content() -> None:
    event = {
        "event": "on_chat_model_end",
        "data": {
            "output": {
                "content": "<think>reason carefully about the failure</think>\nFinal answer."
            }
        },
    }

    assert _extract_model_output_text(event) == "reason carefully about the failure"


def test_stream_event_logging_reports_model_output(caplog) -> None:
    run_names = {"validator-run": "ci-agent-validator"}
    event = {
        "event": "on_chat_model_end",
        "name": "ChatOpenAI",
        "run_id": "model-run",
        "parent_ids": ["validator-run"],
        "data": {
            "output": {
                "content": "<think>inspect validator logs first</think>\nThen answer."
            }
        },
    }

    with caplog.at_level(logging.INFO):
        _log_stream_event(event, run_names)

    assert "[validator] model output: inspect validator logs first" in caplog.text


class RollbackRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.rollback_notes: list[tuple[int, str, str]] = []

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        target = self.config.worktree_root / "app.txt"
        target.write_text("fixed\n", encoding="utf-8")
        _git(self.config.worktree_root, "add", "app.txt")
        _git(self.config.worktree_root, "commit", "-m", "fix(ci): test rollback")
        record = _validator_record(
            self.config,
            attempt_number=attempt_number,
            label="post-fix-validation",
            exit_code=1,
            duration_seconds=1.1,
            stdout="",
            stderr="after failure",
            verdict="SAME_ERROR",
            reason="The error did not change.",
            execution_record="Ran validator after the fix. The same failure remains.",
            next_focus="Change the failing code path instead of this file edit.",
        )
        return ControllerCycleOutcome(
            action="ROLLBACK",
            objective_stage="PASS",
            objective="Make the target command pass.",
            reason="The latest validation still shows the same root cause.",
            fix_summary="Applied a narrow test fix.",
            latest_validator_record=record,
            workers=[
                WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Rollback this attempt."),
                WorkerInvocation(worker_type="fixer", prompt_summary="Apply a narrow fix.", final_text="Changed app.txt and committed it."),
                WorkerInvocation(worker_type="validator", prompt_summary="Validate the fix.", final_text="Same root cause."),
            ],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        self.rollback_notes.append((attempt_number, rollback_to, reason))


class StagedRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.calls = 0

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        self.calls += 1
        output_dir = self.config.worktree_root / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path = output_dir / "result_dubbed.mp4"
        video_path.write_bytes(b"fake-video")
        if self.calls == 1:
            target = self.config.worktree_root / "app.txt"
            target.write_text("faster\n", encoding="utf-8")
            _git(self.config.worktree_root, "add", "app.txt")
            _git(self.config.worktree_root, "commit", "-m", "fix(ci): speed up test path")
            record = _validator_record(
                self.config,
                attempt_number=attempt_number,
                label="post-speed-validation",
                exit_code=0,
                duration_seconds=0.8,
                stdout="ok\n",
                stderr="",
                verdict="PROGRESS",
                reason="The target stayed green and runtime improved.",
                execution_record="Validated the updated worktree and observed a faster successful run.",
                next_focus="Decide whether more speed work is worth it.",
            )
            return ControllerCycleOutcome(
                action="CONTINUE",
                objective_stage="SPEED",
                objective="Reduce target command runtime without changing behavior.",
                reason="The target is green and there is still room to evaluate whether more speed work is worthwhile.",
                fix_summary="Reduced the slow path.",
                latest_validator_record=record,
                workers=[
                    WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Keep the speed improvement and continue."),
                    WorkerInvocation(worker_type="fixer", prompt_summary="Optimize runtime.", final_text="Reduced the slow path."),
                    WorkerInvocation(worker_type="validator", prompt_summary="Validate runtime change.", final_text="Green and faster."),
                ],
            )

        record = _validator_record(
            self.config,
            attempt_number=attempt_number,
            label="steady-state-validation",
            exit_code=0,
            duration_seconds=0.8,
            stdout="ok\n",
            stderr="",
            verdict="PASS",
            reason="The current state is green and good enough to stop.",
            execution_record="Validated the current worktree again and it remains green at the improved runtime.",
        )
        return ControllerCycleOutcome(
            action="DONE",
            objective_stage="SPEED",
            objective="Stop after the current speed improvement.",
            reason="Further optimization is low value relative to the current stable result.",
            fix_summary="No additional code changes were needed.",
            output_dir=str(output_dir),
            review_video_path=str(video_path),
            latest_validator_record=record,
            workers=[
                WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stop here."),
                WorkerInvocation(worker_type="validator", prompt_summary="Confirm the current state.", final_text="Green and stable."),
            ],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("StagedRuntime should not roll back in this test")


class MissingReviewPathRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.calls = 0

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        self.calls += 1
        output_dir = self.config.worktree_root / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path = output_dir / "result_dubbed.mp4"
        video_path.write_bytes(b"fake-video")
        record = _validator_record(
            self.config,
            attempt_number=attempt_number,
            label="steady-state-validation",
            exit_code=0,
            duration_seconds=0.8,
            stdout="ok\n",
            stderr="",
            verdict="PASS",
            reason="The current state is green and good enough to stop.",
            execution_record="Validated the current worktree again and it remains green.",
        )
        if self.calls == 1:
            return ControllerCycleOutcome(
                action="DONE",
                objective_stage="QUALITY",
                objective="Stop without enough evidence.",
                reason="This done request is missing the artifact path and should be rejected.",
                fix_summary="No code changes.",
                latest_validator_record=record,
                workers=[
                    WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Attempt to stop without a review path."),
                    WorkerInvocation(worker_type="validator", prompt_summary="Confirm the current state.", final_text="Green and stable."),
                ],
            )
        return ControllerCycleOutcome(
            action="DONE",
            objective_stage="QUALITY",
            objective="Stop after providing the artifact path.",
            reason="A completed review artifact is now attached to the done request.",
            fix_summary="No code changes.",
            output_dir=str(output_dir),
            review_video_path=str(video_path),
            latest_validator_record=record,
            workers=[
                WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stop with the review path."),
                WorkerInvocation(worker_type="validator", prompt_summary="Confirm the current state.", final_text="Green and stable."),
            ],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("MissingReviewPathRuntime should not roll back in this test")


class PullRequestRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        target = self.config.worktree_root / "app.txt"
        target.write_text("review-worthy\n", encoding="utf-8")
        _git(self.config.worktree_root, "add", "app.txt")
        _git(self.config.worktree_root, "commit", "-m", "fix(ci): prepare review-worthy improvement")
        output_dir = self.config.worktree_root / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path = output_dir / "result_dubbed.mp4"
        video_path.write_bytes(b"fake-video")
        record = _validator_record(
            self.config,
            attempt_number=attempt_number,
            label="steady-state-validation",
            exit_code=0,
            duration_seconds=0.8,
            stdout="ok\n",
            stderr="",
            verdict="PASS",
            reason="The current state is green and review-worthy.",
            execution_record="Validated the current worktree again and it remains green.",
        )
        return ControllerCycleOutcome(
            action="DONE",
            objective_stage="QUALITY",
            objective="Stop after the current validated result.",
            reason="The branch is strong enough to stop and request review.",
            fix_summary="Prepared a coherent review-worthy improvement.",
            output_dir=str(output_dir),
            review_video_path=str(video_path),
            pull_request_request=PullRequestRequest(
                title="feat(video-post): improve published output handling",
                body="## Summary\n- keep the successful published outputs reviewable\n- stop only when the branch is ready for review",
                base_branch="main",
                draft=True,
            ),
            latest_validator_record=record,
            workers=[
                WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stop and request a PR."),
                WorkerInvocation(worker_type="validator", prompt_summary="Confirm the current state.", final_text="Green and stable."),
            ],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("PullRequestRuntime should not roll back in this test")


class PullRequestCapturingOrchestrator(Orchestrator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.created_pull_requests: list[tuple[str, str, str, bool]] = []

    def _maybe_create_pull_request(self, record) -> None:  # type: ignore[override]
        self.created_pull_requests.append(
            (
                record.pull_request_title,
                record.pull_request_body,
                record.pull_request_base_branch,
                record.pull_request_draft,
            )
        )
        record.pull_request_url = "https://github.com/wenming-ma/xiaohongshu-agent/pull/123"
        self.state.pull_request_url = record.pull_request_url
        self.state.pull_request_error = ""
        self._clear_pending_pull_request()


class FakeNotifier:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.messages: list[str] = []
        self.files: list[tuple[str, str]] = []
        self._replies = list(replies or [])

    async def send_message(self, text: str, chat_id: str | None = None, parse_mode: str | None = None) -> str | None:
        self.messages.append(text)
        return "msg-1"

    async def send_file(
        self,
        file_path: Path,
        caption: str = "",
        chat_id: str | None = None,
        *,
        duration: int | None = None,
    ) -> str | None:
        self.files.append((str(file_path), caption))
        if caption:
            self.messages.append(caption)
        return "file-1"

    async def wait_for_reply(self) -> str:
        if self._replies:
            return self._replies.pop(0)
        return "APPROVED"

    def clear_queue(self) -> None:
        return None


def _done_outcome(
    config: ClusterConfig,
    *,
    attempt_number: int,
    prompt: str,
    reason: str = "Validated state is good enough to stop.",
) -> ControllerCycleOutcome:
    output_dir = config.worktree_root / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / "result_dubbed.mp4"
    video_path.write_bytes(b"fake-video")
    record = _validator_record(
        config,
        attempt_number=attempt_number,
        label="steady-state-validation",
        exit_code=0,
        duration_seconds=0.8,
        stdout="ok\n",
        stderr="",
        verdict="PASS",
        reason="The current state is green and good enough to stop.",
        execution_record="Validated the current worktree again and it remains green.",
    )
    return ControllerCycleOutcome(
        action="DONE",
        objective_stage="QUALITY",
        objective="Stop after the current validated result.",
        reason=reason,
        fix_summary="No code changes.",
        output_dir=str(output_dir),
        review_video_path=str(video_path),
        latest_validator_record=record,
        workers=[
            WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stop with the review path."),
            WorkerInvocation(worker_type="validator", prompt_summary="Confirm the current state.", final_text="Green and stable."),
        ],
    )


class RecoveringRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.controller_attempts: list[int] = []
        self.recovery_attempts: list[int] = []

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        self.controller_attempts.append(attempt_number)
        if len(self.controller_attempts) == 1:
            raise RuntimeError("controller crashed on first attempt")
        return _done_outcome(self.config, attempt_number=attempt_number, prompt=prompt)

    async def run_recovery_cycle(self, prompt: str, *, attempt_number: int) -> RecoveryCycleOutcome:
        self.recovery_attempts.append(attempt_number)
        return RecoveryCycleOutcome(
            status="RECOVERED",
            reason="Patched the crash and the same attempt can be retried.",
            fix_summary="Recovered controller execution.",
            validation_notes="No validation run in recovery.",
            workers=[WorkerInvocation(worker_type="recovery", prompt_summary=prompt, final_text="Recovered.")],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("RecoveringRuntime should not roll back in this test")


class AlwaysFailingRecoveryRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.controller_attempts: list[int] = []
        self.recovery_attempts: list[int] = []

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        self.controller_attempts.append(attempt_number)
        raise RuntimeError(f"controller crashed on attempt {attempt_number}")

    async def run_recovery_cycle(self, prompt: str, *, attempt_number: int) -> RecoveryCycleOutcome:
        self.recovery_attempts.append(attempt_number)
        return RecoveryCycleOutcome(
            status="RECOVERED",
            reason="Try the same attempt again.",
            fix_summary="Patched something transient.",
            validation_notes="",
            workers=[WorkerInvocation(worker_type="recovery", prompt_summary=prompt, final_text="Recovered.")],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("AlwaysFailingRecoveryRuntime should not roll back in this test")


class ResetCheckingRecoveryRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.controller_calls = 0
        self.observed_recovery_file_text = ""

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        self.controller_calls += 1
        target = self.config.worktree_root / "app.txt"
        if self.controller_calls == 1:
            target.write_text("broken\n", encoding="utf-8")
            raise RuntimeError("crash after mutating worktree")
        return _done_outcome(self.config, attempt_number=attempt_number, prompt=prompt)

    async def run_recovery_cycle(self, prompt: str, *, attempt_number: int) -> RecoveryCycleOutcome:
        self.observed_recovery_file_text = (self.config.worktree_root / "app.txt").read_text(encoding="utf-8")
        return RecoveryCycleOutcome(
            status="RECOVERED",
            reason="Worktree is back at head_before.",
            fix_summary="Prepared retry.",
            validation_notes="",
            workers=[WorkerInvocation(worker_type="recovery", prompt_summary=prompt, final_text="Recovered.")],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("ResetCheckingRecoveryRuntime should not roll back in this test")


def test_same_error_rolls_back_only_isolated_worktree(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    original_head = _git(repo, "rev-parse", "HEAD")
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"import sys; sys.exit(1)\"",
        max_attempts=1,
        max_consecutive_rollbacks=1,
        sleep_between_attempts=0,
    )
    runtime = RollbackRuntime(config)
    orchestrator = Orchestrator(config, agent_runtime=runtime)  # type: ignore[arg-type]

    success = asyncio.run(orchestrator.run())

    assert success is False
    assert orchestrator.state.status == "stuck"
    assert _git(repo, "rev-parse", "HEAD") == original_head
    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(config.worktree_root, "rev-parse", "HEAD") == original_head
    assert (config.worktree_root / "app.txt").read_text(encoding="utf-8") == "original\n"
    assert runtime.rollback_notes == [(1, original_head, "The error did not change.")]
    assert isinstance(ClusterState.load(config.state_file), ClusterState)


def test_controller_advances_from_continue_to_done(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
        max_attempts=2,
        sleep_between_attempts=0,
    )
    runtime = StagedRuntime(config)
    notifier = FakeNotifier(replies=["继续优化节奏"] * 8 + ["APPROVED"])
    orchestrator = Orchestrator(config, agent_runtime=runtime, notifier=notifier)  # type: ignore[arg-type]

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert orchestrator.state.status == "success"
    assert orchestrator.state.best_success_duration_seconds == 0.8
    assert len(orchestrator.state.attempts) == 10
    assert orchestrator.state.attempts[0].controller_action == "CONTINUE"
    assert orchestrator.state.attempts[0].objective_stage == "SPEED"
    assert orchestrator.state.attempts[0].validator_verdict == "PROGRESS"
    assert orchestrator.state.attempts[-1].controller_action == "DONE"
    assert orchestrator.state.attempts[-1].validator_verdict == "PASS"
    assert len(notifier.messages) == 27
    assert len(notifier.files) == 9
    assert "Controller 请求结束" in notifier.messages[0]
    assert "继续迭代，至少跑到第 10 轮" in notifier.messages[0]
    assert "Attempt: 10/10" in notifier.messages[-3]
    assert orchestrator.state.attempts[-1].video_path.endswith("result_dubbed.mp4")
    assert orchestrator.state.current_user_feedback == "APPROVED"
    assert orchestrator.state.attempts[-1].user_feedback == "APPROVED"


def test_done_request_without_review_video_path_is_rejected(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
        max_attempts=2,
        min_attempts_before_finish=1,
        sleep_between_attempts=0,
    )
    runtime = MissingReviewPathRuntime(config)
    notifier = FakeNotifier(replies=["APPROVED"])
    orchestrator = Orchestrator(config, agent_runtime=runtime, notifier=notifier)  # type: ignore[arg-type]

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert len(orchestrator.state.attempts) == 2
    assert orchestrator.state.attempts[0].controller_action == "DONE"
    assert "review_video_path" in orchestrator.state.attempts[0].controller_reason
    assert orchestrator.state.attempts[0].video_path == ""
    assert notifier.files == [(str(config.worktree_root / "artifacts" / "result_dubbed.mp4"), "本轮生成的视频已附上，请检查内容、字幕、中文配音和整体完成度。")]
    assert "Controller 请求结束" in notifier.messages[0]
    assert orchestrator.state.attempts[-1].video_path.endswith("result_dubbed.mp4")


def test_controller_can_request_pull_request_on_success(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
        max_attempts=1,
        min_attempts_before_finish=1,
        sleep_between_attempts=0,
    )
    runtime = PullRequestRuntime(config)
    notifier = FakeNotifier(replies=["APPROVED"])
    orchestrator = PullRequestCapturingOrchestrator(
        config,
        agent_runtime=runtime,  # type: ignore[arg-type]
        notifier=notifier,
    )

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert orchestrator.state.status == "success"
    assert orchestrator.state.pull_request_url.endswith("/pull/123")
    assert orchestrator.created_pull_requests == [
        (
            "feat(video-post): improve published output handling",
            "## Summary\n- keep the successful published outputs reviewable\n- stop only when the branch is ready for review",
            "main",
            True,
        )
    ]
    record = orchestrator.state.attempts[0]
    assert record.pull_request_requested is True
    assert record.pull_request_url.endswith("/pull/123")
    assert orchestrator.state.pending_pull_request_title == ""


def test_orchestrator_recovers_and_retries_same_attempt_number(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
        max_attempts=1,
        min_attempts_before_finish=1,
        sleep_between_attempts=0,
    )
    runtime = RecoveringRuntime(config)
    notifier = FakeNotifier(replies=["APPROVED"])
    restart_argvs: list[list[str]] = []
    orchestrator = Orchestrator(
        config,
        agent_runtime=runtime,  # type: ignore[arg-type]
        notifier=notifier,
        restart_callback=lambda argv: restart_argvs.append(list(argv)),
    )

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert runtime.controller_attempts == [1, 1]
    assert runtime.recovery_attempts == [1]
    assert len(restart_argvs) == 1
    assert "--resume" in restart_argvs[0]
    assert len(orchestrator.state.recovery_history) == 1
    recovery = orchestrator.state.recovery_history[0]
    assert recovery.status == "RECOVERED"
    assert recovery.restarted is True
    assert len(orchestrator.state.attempts) == 1
    assert orchestrator.state.attempts[0].attempt_number == 1
    assert orchestrator.state.status == "success"


def test_recovery_resets_worktree_to_head_before(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
        max_attempts=1,
        min_attempts_before_finish=1,
        sleep_between_attempts=0,
    )
    runtime = ResetCheckingRecoveryRuntime(config)
    notifier = FakeNotifier(replies=["APPROVED"])
    orchestrator = Orchestrator(
        config,
        agent_runtime=runtime,  # type: ignore[arg-type]
        notifier=notifier,
        restart_callback=lambda argv: None,
    )

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert runtime.observed_recovery_file_text == "original\n"


def test_recovery_limit_marks_session_stuck(tmp_path: Path) -> None:
    repo = _create_repo(tmp_path)
    cache_root = repo / ".cache" / "ci_agent"
    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=cache_root,
        session_id="session123",
        target_command="python -c \"print('ok')\"",
        max_attempts=1,
        min_attempts_before_finish=1,
        max_recovery_attempts_per_attempt=3,
        sleep_between_attempts=0,
    )
    runtime = AlwaysFailingRecoveryRuntime(config)
    orchestrator = Orchestrator(
        config,
        agent_runtime=runtime,  # type: ignore[arg-type]
        restart_callback=lambda argv: None,
    )

    success = asyncio.run(orchestrator.run())

    assert success is False
    assert orchestrator.state.status == "stuck"
    assert runtime.controller_attempts == [1, 1, 1, 1]
    assert runtime.recovery_attempts == [1, 1, 1]
    assert len(orchestrator.state.recovery_history) == 4
    assert orchestrator.state.recovery_history[-1].status == "limit_exceeded"
