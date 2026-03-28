import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.ci_agent.agent_runtime import (
    ControllerCycleOutcome,
    DoneRequest,
    RollbackRequest,
    ValidationCommandRunner,
    ValidationRunReport,
    ValidatorRecord,
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
    assert config.worker_model == "MiniMax-M2.7"
    assert config.worker_base_url == "https://api.minimaxi.com/v1"
    assert config.state_file == repo / ".cache" / "ci_agent" / "sessions" / "session123" / "state.json"
    assert config.log_dir == repo / ".cache" / "ci_agent" / "logs" / "session123"
    assert config.worktree_root == repo / ".cache" / "ci_agent" / "worktrees" / "session123"
    assert config.validator_memory_file == repo / ".cache" / "ci_agent" / "memory" / "session123" / "validator.md"
    assert config.git_branch == "ci-agent/session123"


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
                stdout="ok",
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
            stdout="ok",
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
            latest_validator_record=record,
            workers=[
                WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stop here."),
                WorkerInvocation(worker_type="validator", prompt_summary="Confirm the current state.", final_text="Green and stable."),
            ],
        )

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        raise AssertionError("StagedRuntime should not roll back in this test")


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
    orchestrator = Orchestrator(config, agent_runtime=runtime)  # type: ignore[arg-type]

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert orchestrator.state.status == "success"
    assert orchestrator.state.best_success_duration_seconds == 0.8
    assert len(orchestrator.state.attempts) == 2
    assert orchestrator.state.attempts[0].controller_action == "CONTINUE"
    assert orchestrator.state.attempts[0].objective_stage == "SPEED"
    assert orchestrator.state.attempts[0].validator_verdict == "PROGRESS"
    assert orchestrator.state.attempts[1].controller_action == "DONE"
    assert orchestrator.state.attempts[1].validator_verdict == "PASS"
