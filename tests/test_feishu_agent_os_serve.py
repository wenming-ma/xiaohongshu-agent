from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.agent_os.main_agent import MainAgentDependencies
from src.agent_os.schemas import AgentToolResult
from src.agent_os.tools import AgentTool, AgentToolContext, AgentToolRegistry
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


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
        assert deps.current_user_text == text
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
        self.replies = ["__FORM__:{\"style_pure_color\":true}"]
        self.card_messages = []
        self.form_cards = []

    async def send_message(self, text, *, chat_id=None):
        self.messages.append({"text": text, "chat_id": chat_id})
        return "msg-1"

    async def send_session_card_message(self, session, title, buttons, **kwargs):
        self.card_messages.append(
            {
                "session": session,
                "title": title,
                "buttons": buttons,
                **kwargs,
            }
        )

    async def send_session_form_card(self, session, title, checkers, **kwargs):
        self.form_cards.append(
            {
                "session": session,
                "title": title,
                "checkers": checkers,
                **kwargs,
            }
        )

    async def wait_for_session_image_or_text(self, session, **kwargs):
        return None, self.replies.pop(0)


class FakeRuntime:
    def __init__(self) -> None:
        self.events = []

    def ingest_event(self, event) -> None:
        self.events.append(event)

    def attach_run(self, run) -> None:
        self.run = run


class FakeStore:
    def __init__(self) -> None:
        self.events = []

    def append_event(self, event) -> None:
        self.events.append(event)


class FakeIdleSession:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def wait_for_idle(self) -> None:
        self.order.append("idle")


async def fake_specialist_tool(ctx: AgentToolContext, **params):
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="fake_specialist",
        payload=DeliveryPackage(route="image_post", title=params["spec"]["objective"]),
        summary="queued",
        run_id=ctx.run_id,
        step_id=ctx.step_id or "fake",
    )
    return AgentToolResult(envelope=envelope)


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


@pytest.mark.anyio
async def test_service_waits_for_main_agent_idle_before_polling_next_feishu_event() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    order: list[str] = []
    service = module.FeishuAgentOSService(
        notifier=FakeNotifier(),
        runtime=FakeRuntime(),
        tool_registry=AgentToolRegistry(),
        store=FakeStore(),
        main_agent=object(),
        agent_session=FakeIdleSession(order),
    )

    async def fake_wait_for_next_event():
        order.append("wait")
        return None

    service._wait_for_next_event = fake_wait_for_next_event

    await service.process_next_event_once()

    assert order == ["idle", "wait"]


@pytest.mark.anyio
async def test_prompt_template_search_tool_tolerates_agent_filter_params() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = module.build_default_tool_registry(notifier=FakeNotifier())

    result = await registry.execute(
        "search_prompt_templates",
        module.AgentToolContext(run_id="run-1"),
        query="pure color outfit image prompt",
        content_type="image_post",
        style="pure_color_single_look",
        limit=3,
    )

    assert result.envelope.status == "success"
    assert isinstance(result.envelope.payload, list)


@pytest.mark.anyio
async def test_background_task_tool_accepts_task_type_alias() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=fake_specialist_tool,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_type="image_post",
        spec={"objective": "面试穿搭 5 图"},
    )
    await task_manager.wait_for_all()

    task_summary = result.envelope.payload
    assert result.envelope.status == "success"
    assert task_summary["tool_name"] == "execute_image_post"
    assert task_manager.get_task(task_summary["task_id"]).status == "succeeded"


@pytest.mark.anyio
async def test_background_task_tool_builds_spec_from_direct_agent_params() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=fake_specialist_tool,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_type="image_post",
        objective="做 5 张面试通勤穿搭图，最后只发飞书",
        topic="面试通勤穿搭",
        style_constraints=["纯色背景", "不要模特", "每张图只展示一套衣服"],
        image_count=5,
    )
    await task_manager.wait_for_all()

    task_summary = result.envelope.payload
    started = task_manager.get_task(task_summary["task_id"])
    spec = started.params["spec"]
    assert result.envelope.status == "success"
    assert spec["objective"] == "做 5 张面试通勤穿搭图，最后只发飞书"
    assert spec["topic"] == "面试通勤穿搭"
    assert spec["route"] == "image_post"
    assert spec["style_constraints"] == ["纯色背景", "不要模特", "每张图只展示一套衣服"]
    assert spec["run_options"]["image"]["count"] == 5
    assert started.status == "succeeded"


@pytest.mark.anyio
async def test_background_task_tool_builds_research_budget_from_direct_agent_params() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=fake_specialist_tool,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_type="image_post",
        objective="快速测试 1 张图",
        research_max_items=3,
    )
    await task_manager.wait_for_all()

    task_summary = result.envelope.payload
    spec = task_manager.get_task(task_summary["task_id"]).params["spec"]
    assert result.envelope.status == "success"
    assert spec["run_options"]["research"]["max_items"] == 3


@pytest.mark.anyio
async def test_background_task_tool_lifts_runtime_aliases_from_agent_spec() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=fake_specialist_tool,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_type="image_post",
        spec={
            "objective": "低预算图片实测",
            "route": "image_post",
            "topic": "周末徒步轻量装备",
            "image_count": 1,
            "research_max_items": 2,
            "image_generation_concurrency": 1,
        },
    )
    await task_manager.wait_for_all()

    task_summary = result.envelope.payload
    spec = task_manager.get_task(task_summary["task_id"]).params["spec"]
    assert result.envelope.status == "success"
    assert spec["run_options"]["image"]["count"] == 1
    assert spec["run_options"]["image"]["concurrency"] == 1
    assert spec["run_options"]["research"]["max_items"] == 2


@pytest.mark.anyio
async def test_background_task_tool_uses_current_user_text_for_omitted_runtime_aliases() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=fake_specialist_tool,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(
            run_id="run-1",
            metadata={
                "current_user_text": (
                    "图片数量=1；research_max_items=2；"
                    "image_generation_concurrency=1；最终只发飞书。"
                )
            },
        ),
        task_type="image_post",
        objective="创建雨天通勤包内物品图文",
        topic="雨天通勤包内物品",
    )
    await task_manager.wait_for_all()

    task_summary = result.envelope.payload
    spec = task_manager.get_task(task_summary["task_id"]).params["spec"]
    assert result.envelope.status == "success"
    assert spec["run_options"]["image"]["count"] == 1
    assert spec["run_options"]["image"]["concurrency"] == 1
    assert spec["run_options"]["research"]["max_items"] == 2


@pytest.mark.anyio
async def test_background_task_tool_rejects_empty_route_request_without_starting_task() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=fake_specialist_tool,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_type="image_post",
    )

    assert result.envelope.status == "error"
    assert "TaskRunSpec" in (result.envelope.error_message or "")
    assert task_manager.list_tasks() == []


@pytest.mark.anyio
async def test_cancel_background_task_tool_cancels_running_task() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    started = asyncio.Event()
    never_release = asyncio.Event()

    async def wait_until_cancelled(ctx: AgentToolContext, **params):
        started.set()
        await never_release.wait()

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Fake image specialist",
            execute=wait_until_cancelled,
            category="specialist",
        )
    )
    task_manager = module.AgentOSTaskManager(tool_registry=registry)
    module._register_task_tools(registry, task_manager=task_manager)

    start_result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_type="image_post",
        objective="取消测试",
    )
    task_id = start_result.envelope.payload["task_id"]
    await started.wait()

    cancel_result = await registry.execute(
        "cancel_background_agent_task",
        AgentToolContext(run_id="run-1"),
        task_id=task_id,
    )
    await task_manager.wait_for_all()

    assert cancel_result.envelope.status == "success"
    assert task_manager.get_task(task_id).status == "cancelled"


def test_default_agent_os_registry_exposes_routes_resources_and_feishu_tools() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = module.build_default_tool_registry(notifier=FakeNotifier())
    tool_names = {item["name"] for item in registry.describe_tools()}

    assert "execute_image_post" in tool_names
    assert "execute_article_post" in tool_names
    assert "execute_video_post" in tool_names
    assert "list_skills" in tool_names
    assert "search_prompt_templates" in tool_names
    assert "feishu_ask_single_choice" in tool_names
    assert "feishu_ask_multi_select" in tool_names
    assert "feishu_send_progress" in tool_names
    assert "ask_feishu_single_choice" not in tool_names
    assert "ask_feishu_multi_select" not in tool_names
    assert "send_feishu_progress" not in tool_names
    assert "start_background_agent_task" in tool_names
    assert "list_background_agent_tasks" in tool_names
    assert "restart_background_agent_task" in tool_names
    assert "cancel_background_agent_task" in tool_names


@pytest.mark.anyio
async def test_feishu_multi_select_tool_renders_form_and_returns_reply() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    notifier = FakeNotifier()
    registry = module.build_default_tool_registry(notifier=notifier)
    session = object()

    result = await registry.execute(
        "feishu_ask_multi_select",
        AgentToolContext(run_id="run-1", session=session),
        title="选择图片约束",
        options_spec="纯色背景::style_pure_color||不要人物::style_no_people",
        phase="clarify_style",
        input_name="extra_requirements",
        input_placeholder="其他要求",
        submit_label="确认",
    )

    assert result.envelope.status == "success"
    assert result.envelope.payload["reply"].startswith("__FORM__:")
    assert notifier.form_cards[0]["title"] == "选择图片约束"
    assert notifier.form_cards[0]["checkers"][0]["name"] == "style_pure_color"


@pytest.mark.anyio
async def test_feishu_multi_select_tool_accepts_question_alias_from_main_agent() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    notifier = FakeNotifier()
    registry = module.build_default_tool_registry(notifier=notifier)

    result = await registry.execute(
        "feishu_ask_multi_select",
        AgentToolContext(run_id="run-1", session=object()),
        question="请选择图片风格约束",
        options_spec="纯色背景::style_pure_color||不要人物::style_no_people",
        allow_custom_text=True,
    )

    assert result.envelope.status == "success"
    assert notifier.form_cards[0]["title"] == "请选择图片风格约束"
    assert notifier.form_cards[0]["input_name"] == "custom_text"


@pytest.mark.anyio
async def test_feishu_single_choice_tool_accepts_question_alias_from_main_agent() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    notifier = FakeNotifier()
    notifier.replies = ["image_post"]
    registry = module.build_default_tool_registry(notifier=notifier)

    result = await registry.execute(
        "feishu_ask_single_choice",
        AgentToolContext(run_id="run-1", session=object()),
        question="请选择内容路线",
        options_spec="图文::image_post||文章::article_post",
        allow_custom_text=False,
    )

    assert result.envelope.status == "success"
    assert notifier.card_messages[0]["title"] == "请选择内容路线"


def test_task_tool_description_includes_spec_contract_for_main_agent() -> None:
    module = importlib.import_module("src.apps.feishu_agent_os.serve")
    registry = module.build_default_tool_registry(notifier=FakeNotifier())
    descriptions = {item["name"]: item["description"] for item in registry.describe_tools()}

    assert "params.spec" in descriptions["start_background_agent_task"]
    assert "objective" in descriptions["start_background_agent_task"]
    assert "delimited" in descriptions["feishu_ask_multi_select"]
