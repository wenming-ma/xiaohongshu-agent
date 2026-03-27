from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ClusterConfig:
    model: str = "claude-sonnet-4-6"
    target_command: str = ""
    target_timeout: int = 600

    # Limits
    max_attempts: int = 20
    max_consecutive_rollbacks: int = 3
    max_worker_turns: int = 30
    sleep_between_attempts: int = 5

    # Paths
    project_root: Path = PROJECT_ROOT
    state_file: Path = PROJECT_ROOT / "scripts" / "ci_agent" / "state.json"
    log_dir: Path = PROJECT_ROOT / "scripts" / "ci_agent" / "logs"
    git_branch: str | None = None

    # run.ps1 env var defaults
    default_env_vars: dict[str, str] = field(default_factory=lambda: {
        "VIDEO_DUB_TTS_PROVIDER": "s2cpp",
        "VIDEO_DUB_USE_SEPARATE_ENV": "1",
        "VIDEO_DUB_REQUIRE_AUDIO_ENV": "1",
        "S2CPP_TTS_BASE_URL": "http://127.0.0.1:3030",
        "S2CPP_TTS_REFERENCE_AUDIO_PATH": "submodules/s2.cpp_check/references/BV1Lm4y1B7wb_30s.wav",
        "S2CPP_TTS_CONCURRENCY": "1",
        "S2CPP_TTS_TIMEOUT_SECONDS": "240",
        "S2CPP_TTS_MERGE_SEGMENTS": "1",
        "S2CPP_TTS_MERGE_MAX_GAP": "1.2",
        "S2CPP_TTS_MERGE_MAX_DURATION": "12",
        "S2CPP_TTS_MERGE_MAX_CHARS": "120",
    })

    @classmethod
    def from_env(cls, **overrides) -> ClusterConfig:
        load_dotenv(PROJECT_ROOT / ".env")
        default_target = (
            "uv run python workshop/video_post/run.py"
            " --topics-file workshop/video_post/topics.json"
            " --limit 1 --no-publish --no-feishu"
        )
        kwargs: dict = {"target_command": default_target}
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
        return env
