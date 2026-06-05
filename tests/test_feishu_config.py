from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_feishu_config(env_updates: dict[str, str]) -> tuple[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("FEISHU_") and key != "APP_ENV"
    }
    env.update(env_updates)
    code = (
        "from src.config.settings import FeishuConfig\n"
        "print(FeishuConfig.RUNTIME_ENV)\n"
        "print(FeishuConfig.CHAT_ID)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    runtime_env, chat_id = result.stdout.strip().splitlines()
    return runtime_env, chat_id


def test_feishu_config_uses_dev_chat_id_by_default() -> None:
    runtime_env, chat_id = _read_feishu_config(
        {
            "FEISHU_CHAT_DEV_ID": "oc_test",
            "FEISHU_CHAT_DEPLOY_ID": "oc_deploy",
        }
    )

    assert runtime_env == "dev"
    assert chat_id == "oc_test"


def test_feishu_config_uses_deploy_chat_id_for_deploy_runtime() -> None:
    runtime_env, chat_id = _read_feishu_config(
        {
            "FEISHU_RUNTIME_ENV": "deploy",
            "FEISHU_CHAT_DEV_ID": "oc_test",
            "FEISHU_CHAT_DEPLOY_ID": "oc_deploy",
        }
    )

    assert runtime_env == "deploy"
    assert chat_id == "oc_deploy"


def test_feishu_config_keeps_legacy_chat_id_as_explicit_override() -> None:
    runtime_env, chat_id = _read_feishu_config(
        {
            "FEISHU_RUNTIME_ENV": "deploy",
            "FEISHU_CHAT_ID": "oc_override",
            "FEISHU_CHAT_DEV_ID": "oc_test",
            "FEISHU_CHAT_DEPLOY_ID": "oc_deploy",
        }
    )

    assert runtime_env == "deploy"
    assert chat_id == "oc_override"

