from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load_serve_module():
    path = Path(__file__).resolve().parents[1] / "src" / "apps" / "feishu_orchestrator" / "serve.py"
    spec = importlib.util.spec_from_file_location("feishu_orchestrator_serve_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apply_feishu_interactive_defaults_preserves_explicit_env(monkeypatch) -> None:
    module = _load_serve_module()
    monkeypatch.delenv("RESEARCH_MIN_POSTS_RESEARCHED", raising=False)
    monkeypatch.setenv("RESEARCH_VALIDATION_MAX_RETRIES", "9")
    monkeypatch.delenv("VERTEX_AI_VISION_MAX_CONCURRENCY", raising=False)

    module.apply_feishu_interactive_defaults()

    assert os.environ["RESEARCH_MIN_POSTS_RESEARCHED"] == "3"
    assert os.environ["RESEARCH_VALIDATION_MAX_RETRIES"] == "9"
    assert os.environ["VERTEX_AI_VISION_MAX_CONCURRENCY"] == "3"


def test_apply_feishu_interactive_defaults_allow_formal_research_retry(monkeypatch) -> None:
    module = _load_serve_module()
    for key in module.FEISHU_INTERACTIVE_ENV_DEFAULTS:
        monkeypatch.delenv(key, raising=False)

    module.apply_feishu_interactive_defaults()

    assert os.environ["RESEARCH_VALIDATION_MAX_RETRIES"] == "3"


def test_feishu_orchestrator_serve_delegates_to_agent_os() -> None:
    module = _load_serve_module()

    assert module.create_service.__module__ == "src.apps.feishu_agent_os.serve"
    assert module.main_async.__module__ == "src.apps.feishu_agent_os.serve"
