from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


def _load_module(script_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_outfit_runner_returns_blocked_status_when_session_is_not_acquired(monkeypatch):
    script_path = Path("workshop/outfit_post/run.py").resolve()
    module = _load_module(script_path, "outfit_post_run_for_sessions")

    class _NeverPipeline:
        def __init__(self, *args, **kwargs):
            raise AssertionError("pipeline should not start when interactive session is blocked")

    async def _fake_acquire_session(**kwargs):
        return None, "blocked_active_session"

    async def _fake_finalize_session(session, *, status):
        raise AssertionError("finalize should not be called without an acquired session")

    monkeypatch.setattr(module, "OutfitPostPipeline", _NeverPipeline)
    monkeypatch.setattr(module, "acquire_interactive_session", _fake_acquire_session)
    monkeypatch.setattr(module, "finalize_interactive_session", _fake_finalize_session)

    result = asyncio.run(
        module.run_single(
            {"topic": "", "audience": "20-30岁女性", "items": ""},
            idx=1,
            total=1,
            max_retries=1,
            retry_delay=0,
            publish=False,
            mock=False,
            notify_feishu=False,
        )
    )

    assert result["success"] is False
    assert result["run_status"] == "blocked"
    assert "blocked_active_session" in result["error_message"]
