from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_os.main_agent import MainAgentDependencies
from src.agent_os.runtime import MainAgentRuntime
from src.agent_os.store import AgentOSStore
from src.agent_os.tools import AgentToolRegistry
from src.apps.feishu_agent_os.serve import AgentOSMainAgentSession, FeishuAgentOSService


class FakeRunResult:
    def __init__(self, output: str, messages: list[str]) -> None:
        self.output = output
        self._messages = messages

    def all_messages(self) -> list[str]:
        return list(self._messages)


class PlanningProbeAgent:
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
        return FakeRunResult(
            f"planned:{len(self.calls)}",
            [*message_history, text, f"planned:{len(self.calls)}"],
        )


class QueueNotifier:
    client = None
    chat_id = "chat-real-case"

    def __init__(self, events):
        self.events = list(events)
        self.messages = []
        self.started = False

    async def start_polling(self):
        self.started = True

    async def wait_for_image_or_text(self):
        if not self.events:
            raise RuntimeError("no more fake Feishu events")
        return self.events.pop(0)

    async def send_message(self, text, *, chat_id=None):
        self.messages.append({"text": text, "chat_id": chat_id})
        return f"msg-{len(self.messages)}"


class FakeFeishuInputEvent:
    def __init__(self, *, text: str, action: str = "button", image_path=None) -> None:
        self.text = text
        self.action = action
        self.image_path = image_path


def build_service(tmp_path: Path, notifier: QueueNotifier, agent: PlanningProbeAgent) -> FeishuAgentOSService:
    return FeishuAgentOSService(
        notifier=notifier,
        runtime=MainAgentRuntime(),
        tool_registry=AgentToolRegistry(),
        store=AgentOSStore(tmp_path / "agent-os"),
        main_agent=agent,
        acquire_session=None,
    )


@pytest.mark.anyio
async def test_realistic_text_requests_are_inserted_into_main_agent_session(tmp_path: Path) -> None:
    agent = PlanningProbeAgent()
    notifier = QueueNotifier(
        [
            (
                None,
                "做 5 张图，主题是面试通勤穿搭，纯色背景，不要模特，每张图只展示一套衣服。",
            ),
            (
                None,
                "换成登山场景，图片数量你根据分组自己定，最后发飞书。",
            ),
        ]
    )
    service = build_service(tmp_path, notifier, agent)

    await service._start_main_agent_session()
    await service.process_next_event_once()
    await service.agent_session.wait_for_idle()
    await service.process_next_event_once()
    await service.agent_session.wait_for_idle()
    await service.agent_session.stop()

    assert agent.calls[0]["text"].startswith("做 5 张图")
    assert "登山场景" in agent.calls[1]["text"]
    assert agent.calls[1]["message_history"] == [
        agent.calls[0]["text"],
        "planned:1",
    ]
    assert notifier.messages == []
    assert service.store.read_events()[0].text.startswith("做 5 张图")


@pytest.mark.anyio
async def test_reference_image_request_is_inserted_with_path_and_caption(tmp_path: Path) -> None:
    image_path = tmp_path / "reference.jpg"
    image_path.write_bytes(b"fake-image")
    agent = PlanningProbeAgent()
    notifier = QueueNotifier([(image_path, "参考这张图的衣服版型，生成新的穿搭图。")])
    service = build_service(tmp_path, notifier, agent)

    await service._start_main_agent_session()
    await service.process_next_event_once()
    await service.agent_session.wait_for_idle()
    await service.agent_session.stop()

    inserted = agent.calls[0]["text"]
    assert "[用户发送图片]" in inserted
    assert str(image_path) in inserted
    assert "参考这张图的衣服版型" in inserted


@pytest.mark.anyio
async def test_new_session_control_discards_previous_conversation_context(tmp_path: Path) -> None:
    agent = PlanningProbeAgent()
    notifier = QueueNotifier(
        [
            (None, "先做一篇咖啡店探店图文。"),
            (None, "__control__:new_session"),
            (None, "新开会话：做 3 张极简产品海报。"),
        ]
    )
    service = build_service(tmp_path, notifier, agent)

    await service._start_main_agent_session()
    await service.process_next_event_once()
    await service.agent_session.wait_for_idle()
    await service.process_next_event_once()
    await service.process_next_event_once()
    await service.agent_session.wait_for_idle()
    await service.agent_session.stop()

    assert len(agent.calls) == 2
    assert agent.calls[1]["text"].startswith("新开会话")
    assert agent.calls[1]["message_history"] == []


@pytest.mark.anyio
async def test_empty_feishu_poll_result_is_ignored(tmp_path: Path) -> None:
    agent = PlanningProbeAgent()
    notifier = QueueNotifier([(None, "")])
    service = build_service(tmp_path, notifier, agent)

    await service._start_main_agent_session()
    event = await service.process_next_event_once()
    await service.agent_session.wait_for_idle()
    await service.agent_session.stop()

    assert event is None
    assert agent.calls == []
    assert service.store.read_events() == []


def test_feishu_button_action_preserves_button_text_as_user_message(tmp_path: Path) -> None:
    agent = PlanningProbeAgent()
    service = build_service(tmp_path, QueueNotifier([]), agent)

    event = service._event_from_feishu_input(
        FakeFeishuInputEvent(
            text="做 5 张面试穿搭图片，纯色背景，不要人物。",
            action="button",
        )
    )

    assert event is not None
    assert event.kind == "text"
    assert event.text.startswith("做 5 张面试穿搭")
