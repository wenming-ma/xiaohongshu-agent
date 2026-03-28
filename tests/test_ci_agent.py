import asyncio
import subprocess
from pathlib import Path

from scripts.ci_agent.agent_runtime import ControllerOutcome, ValidationOutcome
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


def test_cluster_config_defaults_to_isolated_cache_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

    config = ClusterConfig.from_env(
        project_root=repo,
        cache_root=repo / ".cache" / "ci_agent",
        session_id="session123",
    )

    assert config.model == "openai:gpt-5.4"
    assert config.state_file == repo / ".cache" / "ci_agent" / "sessions" / "session123" / "state.json"
    assert config.worktree_root == repo / ".cache" / "ci_agent" / "worktrees" / "session123"
    assert config.git_branch == "ci-agent/session123"


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


class FakeRuntime:
    def __init__(self, worktree_root: Path):
        self.worktree_root = worktree_root

    async def run_controller(self, prompt: str) -> ControllerOutcome:
        worker = WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stay on PASS.")
        return ControllerOutcome(
            stage="PASS",
            objective="Make the target command pass.",
            reason="The baseline target command is failing.",
            fixer_system_overlay="Stay narrow and restore a passing target command.",
            validator_system_overlay="Judge only whether the failure meaningfully changed.",
            worker=worker,
        )

    async def run_fixer(self, prompt: str, system_overlay: str = "") -> WorkerInvocation:
        assert "passing target command" in system_overlay
        target = self.worktree_root / "app.txt"
        target.write_text("fixed\n", encoding="utf-8")
        _git(self.worktree_root, "add", "app.txt")
        _git(self.worktree_root, "commit", "-m", "fix(ci): test rollback")
        return WorkerInvocation(worker_type="fixer", prompt_summary=prompt, final_text="Applied a test fix.")

    async def run_validator(self, prompt: str, system_overlay: str = "") -> ValidationOutcome:
        assert "failure meaningfully changed" in system_overlay
        worker = WorkerInvocation(worker_type="validator", prompt_summary=prompt, final_text="Same root cause.")
        return ValidationOutcome(verdict="SAME_ERROR", reason="The error did not change.", worker=worker)


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
    runtime = FakeRuntime(config.worktree_root)
    orchestrator = Orchestrator(config, agent_runtime=runtime)

    results = [(-1, "", "before failure", 1.0), (-1, "", "after failure", 1.1)]

    def fake_run_target() -> tuple[int, str, str, float]:
        return results.pop(0)

    orchestrator._run_target = fake_run_target  # type: ignore[method-assign]

    success = asyncio.run(orchestrator.run())

    assert success is False
    assert orchestrator.state.status == "stuck"
    assert _git(repo, "rev-parse", "HEAD") == original_head
    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(config.worktree_root, "rev-parse", "HEAD") == original_head
    assert (config.worktree_root / "app.txt").read_text(encoding="utf-8") == "original\n"
    assert isinstance(ClusterState.load(config.state_file), ClusterState)


class StagedRuntime:
    def __init__(self, worktree_root: Path):
        self.worktree_root = worktree_root
        self.controller_calls = 0

    async def run_controller(self, prompt: str) -> ControllerOutcome:
        self.controller_calls += 1
        if self.controller_calls == 1:
            worker = WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Optimize speed.")
            return ControllerOutcome(
                stage="SPEED",
                objective="Reduce target command runtime without changing behavior.",
                reason="The target command already passes, so speed is the next priority.",
                fixer_system_overlay="Prefer measurable runtime wins. Avoid semantic changes.",
                validator_system_overlay="Treat runtime reduction with a green target as progress.",
                worker=worker,
            )
        worker = WorkerInvocation(worker_type="controller", prompt_summary=prompt, final_text="Stop here.")
        return ControllerOutcome(
            stage="DONE",
            objective="Stop. The current green baseline is good enough.",
            reason="Recent attempts already achieved the current optimization goal.",
            fixer_system_overlay="Do not make further edits.",
            validator_system_overlay="No validation needed if the controller stops.",
            worker=worker,
        )

    async def run_fixer(self, prompt: str, system_overlay: str = "") -> WorkerInvocation:
        assert "runtime wins" in system_overlay
        target = self.worktree_root / "app.txt"
        target.write_text("faster\n", encoding="utf-8")
        _git(self.worktree_root, "add", "app.txt")
        _git(self.worktree_root, "commit", "-m", "fix(ci): speed up test path")
        return WorkerInvocation(worker_type="fixer", prompt_summary=prompt, final_text="Reduced the slow path.")

    async def run_validator(self, prompt: str, system_overlay: str = "") -> ValidationOutcome:
        assert "runtime reduction" in system_overlay
        worker = WorkerInvocation(worker_type="validator", prompt_summary=prompt, final_text="Speed improvement looks real.")
        return ValidationOutcome(verdict="PROGRESS", reason="The target stayed green and runtime improved.", worker=worker)


def test_controller_advances_from_speed_to_done(tmp_path: Path) -> None:
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
    runtime = StagedRuntime(config.worktree_root)
    orchestrator = Orchestrator(config, agent_runtime=runtime)

    results = [
        (0, "ok", "", 1.2),
        (0, "ok", "", 0.8),
        (0, "ok", "", 0.8),
    ]

    def fake_run_target() -> tuple[int, str, str, float]:
        return results.pop(0)

    orchestrator._run_target = fake_run_target  # type: ignore[method-assign]

    success = asyncio.run(orchestrator.run())

    assert success is True
    assert orchestrator.state.status == "success"
    assert orchestrator.state.best_success_duration_seconds == 0.8
    assert len(orchestrator.state.attempts) == 2
    assert orchestrator.state.attempts[0].objective_stage == "SPEED"
    assert orchestrator.state.attempts[0].validator_verdict == "PROGRESS"
    assert orchestrator.state.attempts[1].objective_stage == "DONE"
