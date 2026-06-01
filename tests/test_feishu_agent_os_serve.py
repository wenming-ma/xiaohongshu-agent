from __future__ import annotations

import importlib


def test_feishu_agent_os_serve_module_imports() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")

    assert hasattr(module, "create_service")
    assert hasattr(module, "main")


def test_create_service_wires_runtime_and_notifier() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    service = module.create_service(notifier=object())

    assert hasattr(service, "runtime")
    assert hasattr(service, "serve_forever")
