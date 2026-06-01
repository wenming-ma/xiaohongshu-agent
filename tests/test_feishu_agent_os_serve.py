from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.agent_os.main_agent import MainAgentDependencies


class FakeRunResult:
    def __init__(self, output: str, messages: list[str]) -> None:
        self.output = output
        self._messages = messages

    def all_messages(self) -> list[str]:
        return list(self._messages)


class FakeAgent:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, text, *, deps, message_history):
        self.calls.append(
            {
                "text": text,
                "deps": deps,
                "message_history": list(message_history),
            }
        )
        return FakeRunResult(f"echo:{text}", [*message_history, text, f"echo:{text}"])


class FakeNotifier:
    def __init__(self) -> None:
        self.messages = []

    async def send_message(self, text, *, chat_id=None):
        self.messages.append({"text": text, "chat_id": chat_id})
        return "msg-1"


def test_feishu_agent_os_serve_module_imports() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")

    assert hasattr(module, "create_service")
    assert hasattr(module, "main")


def test_create_service_wires_runtime_and_notifier() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    service = module.create_service(notifier=object())

    assert hasattr(service, "runtime")
    assert hasattr(service, "serve_forever")
    assert service.task_manager is not None


def test_serve_module_loads_dotenv_before_feishu_config_initializes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / ".env").exists():
        pytest.skip("local .env is required for import-order regression coverage")

    env = dict(os.environ)
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHAT_ID"):
        env.pop(key, None)
    code = (
        "import src.apps.feishu_agent_os.serve\n"
        "from src.config.settings import FeishuConfig\n"
        "print('ready=' + str(bool(FeishuConfig.APP_ID and FeishuConfig.APP_SECRET and FeishuConfig.CHAT_ID)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "ready=True" in result.stdout


@pytest.mark.anyio
async def test_agent_os_main_session_processes_inserted_messages_sequentially() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    agent = FakeAgent()
    notifier = FakeNotifier()
    deps = MainAgentDependencies(chat_id="chat-1")
    session = module.AgentOSMainAgentSession(
        agent=agent,
        deps=deps,
        notifier=notifier,
    )

    session.start()
    session.enqueue("第一条")
    await session.wait_for_idle()
    session.enqueue("第二条")
    await session.wait_for_idle()
    await session.stop()

    assert [call["text"] for call in agent.calls] == ["第一条", "第二条"]
    assert agent.calls[1]["message_history"] == ["第一条", "echo:第一条"]
    assert notifier.messages[-1]["text"] == "echo:第二条"
    assert notifier.messages[-1]["chat_id"] == "chat-1"


@pytest.mark.anyio
async def test_agent_os_main_session_reset_discards_conversation_history() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    agent = FakeAgent()
    session = module.AgentOSMainAgentSession(
        agent=agent,
        deps=MainAgentDependencies(),
    )

    session.start()
    session.enqueue("旧会话")
    await session.wait_for_idle()
    session.reset_session()
    session.enqueue("新会话")
    await session.wait_for_idle()
    await session.stop()

    assert agent.calls[-1]["text"] == "新会话"
    assert agent.calls[-1]["message_history"] == []


def test_default_agent_os_registry_exposes_routes_resources_and_feishu_tools() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = module.build_default_tool_registry(notifier=FakeNotifier())
    tool_names = {item["name"] for item in registry.describe_tools()}

    assert "execute_image_post" in tool_names
    assert "execute_article_post" in tool_names
    assert "execute_video_post" in tool_names
    assert "list_skills" in tool_names
    assert "search_prompt_templates" in tool_names
    assert "ask_feishu_single_choice" in tool_names
    assert "start_background_agent_task" in tool_names
    assert "list_background_agent_tasks" in tool_names
    assert "restart_background_agent_task" in tool_names
