from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_run_module():
    path = Path(__file__).resolve().parents[1] / "workshop" / "feishu_orchestrator" / "run.py"
    spec = importlib.util.spec_from_file_location("feishu_orchestrator_run_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_script_applies_interactive_defaults_without_overriding_env(monkeypatch) -> None:
    module = load_run_module()
    for key in module.FEISHU_INTERACTIVE_ENV_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RESEARCH_MIN_POSTS_RESEARCHED", "7")

    module.apply_feishu_interactive_defaults()

    assert os.environ["RESEARCH_MIN_POSTS_RESEARCHED"] == "7"
    assert os.environ["RESEARCH_VALIDATION_MAX_RETRIES"] == "3"
    assert os.environ["VERTEX_AI_IMAGE_MAX_CONCURRENCY"] == "1"
