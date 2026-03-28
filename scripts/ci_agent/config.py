from __future__ import annotations
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = PROJECT_ROOT / ".cache" / "ci_agent"
RUNBOOK_FILE = PROJECT_ROOT / "scripts" / "ci_agent" / "AGENTS.md"


@dataclass(frozen=True)
class ClusterConfig:
    session_id: str = ""
    # Backward-compatible: `model` is the controller model.
    model: str = "openai:gpt-5.4"
    controller_max_retries: int = 20
    controller_timeout_seconds: int = 300
    worker_model: str = "MiniMax-M2.7"
    worker_base_url: str = "https://api.minimaxi.com/v1"
    target_command: str = ""
    target_timeout: int = 600

    # Limits
    max_attempts: int = 20
    min_attempts_before_finish: int = 10
    max_consecutive_rollbacks: int = 3
    max_recovery_attempts_per_attempt: int = 3
    max_worker_turns: int = 30
    sleep_between_attempts: int = 5

    # Paths
    project_root: Path = PROJECT_ROOT
    cache_root: Path = CACHE_ROOT
    state_file: Path = CACHE_ROOT / "sessions" / "default" / "state.json"
    log_dir: Path = CACHE_ROOT / "logs" / "default"
    worktree_root: Path = CACHE_ROOT / "worktrees" / "default"
    controller_memory_file: Path = CACHE_ROOT / "memory" / "default" / "controller.md"
    validator_memory_file: Path = CACHE_ROOT / "memory" / "default" / "validator.md"
    git_branch: str = "ci-agent/default"
    runbook_file: Path = RUNBOOK_FILE

    # run.ps1 env var defaults
    default_env_vars: dict[str, str] = field(default_factory=lambda: {
        "VIDEO_DUB_TTS_PROVIDER": "s2cpp",
        "VIDEO_DUB_USE_SEPARATE_ENV": "1",
        "VIDEO_DUB_REQUIRE_AUDIO_ENV": "1",
        "S2CPP_TTS_BASE_URL": "http://127.0.0.1:3030",
        "S2CPP_TTS_CONCURRENCY": "1",
        "S2CPP_TTS_TIMEOUT_SECONDS": "240",
        "S2CPP_TTS_MERGE_SEGMENTS": "1",
        "S2CPP_TTS_MERGE_MAX_GAP": "1.2",
        "S2CPP_TTS_MERGE_MAX_DURATION": "12",
        "S2CPP_TTS_MERGE_MAX_CHARS": "120",
    })

    @classmethod
    def from_env(cls, **overrides) -> ClusterConfig:
        project_root = Path(overrides.get("project_root", PROJECT_ROOT))
        cache_root = Path(overrides.get("cache_root", project_root / ".cache" / "ci_agent"))
        session_id = overrides.get("session_id") or uuid.uuid4().hex[:12]
        default_target = (
            "uv run python workshop/video_post/run.py"
            " --topics-file workshop/video_post/topics.json"
            " --limit 1 --no-publish"
        )
        load_dotenv(project_root / ".env")
        kwargs: dict = {
            "session_id": session_id,
            "project_root": project_root,
            "cache_root": cache_root,
            "worker_model": os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7"),
            "worker_base_url": os.environ.get(
                "MINIMAX_OPENAI_BASE_URL",
                os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
            ),
            "state_file": cache_root / "sessions" / session_id / "state.json",
            "log_dir": cache_root / "logs" / session_id,
            "worktree_root": cache_root / "worktrees" / session_id,
            "controller_memory_file": cache_root / "memory" / session_id / "controller.md",
            "validator_memory_file": cache_root / "memory" / session_id / "validator.md",
            "git_branch": f"ci-agent/{session_id}",
            "runbook_file": project_root / "scripts" / "ci_agent" / "AGENTS.md",
            "target_command": default_target,
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    def build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for k, v in self.default_env_vars.items():
            env.setdefault(k, v)
        audio_python = self.project_root / ".venv-audio" / "Scripts" / "python.exe"
        if audio_python.exists():
            env.setdefault("VIDEO_DUB_AUDIO_PYTHON", str(audio_python))
        else:
            unix_path = self.project_root / ".venv-audio" / "bin" / "python"
            if unix_path.exists():
                env.setdefault("VIDEO_DUB_AUDIO_PYTHON", str(unix_path))
        env.setdefault("CI_AGENT_SESSION_ID", self.session_id)
        env.setdefault("CI_AGENT_SOURCE_ROOT", str(self.project_root))
        env.setdefault("CI_AGENT_WORKTREE_ROOT", str(self.worktree_root))
        env.setdefault("CI_AGENT_ANALYSIS_ROOT", str(self.cache_root / "analysis" / self.session_id))
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def build_worker_model(self) -> ChatOpenAI:
        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            msg = "MINIMAX_API_KEY is not set"
            raise RuntimeError(msg)
        return ChatOpenAI(
            model=self.worker_model,
            api_key=api_key,
            base_url=self.worker_base_url,
        )

    def build_controller_model(self) -> ChatOpenAI:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            msg = "OPENAI_API_KEY is not set"
            raise RuntimeError(msg)
        model_name = self.model.split(":", 1)[1] if self.model.startswith("openai:") else self.model
        base_url = os.environ.get("OPENAI_BASE_URL")
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout=self.controller_timeout_seconds,
            max_retries=self.controller_max_retries,
            use_responses_api=False,
            output_version="v0",
        )
