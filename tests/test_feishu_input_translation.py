from __future__ import annotations

from pathlib import Path

from src.orchestration.agent_events import AgentEventBridge
from src.orchestration.feishu_translation import FeishuInputTranslator
from src.utils.feishu_notifier import FeishuInputEvent


class FakeAgentRun:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []
        self.reset_calls = 0

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.enqueued.append((text, priority))

    def reset_session(self) -> None:
        self.reset_calls += 1


def test_feishu_text_event_is_inserted_as_plain_user_message() -> None:
    run = FakeAgentRun()
    bridge = AgentEventBridge()
    bridge.attach_run(run)
    translator = FeishuInputTranslator(bridge=bridge)

    translator.ingest(FeishuInputEvent(kind="text", text="帮我做一组通勤穿搭图"))

    assert run.enqueued == [("帮我做一组通勤穿搭图", "asap")]


def test_feishu_image_event_is_inserted_as_plain_user_message(tmp_path: Path) -> None:
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"image")
    run = FakeAgentRun()
    bridge = AgentEventBridge()
    bridge.attach_run(run)
    translator = FeishuInputTranslator(bridge=bridge)

    translator.ingest(
        FeishuInputEvent(
            kind="image",
            text="参考这张图里的衣服",
            image_path=reference,
        ),
        priority="when_idle",
    )

    message, priority = run.enqueued[0]
    assert priority == "when_idle"
    assert "[用户发送图片]" in message
    assert str(reference) in message
    assert "参考这张图里的衣服" in message


def test_feishu_form_and_button_events_are_still_plain_user_messages() -> None:
    run = FakeAgentRun()
    bridge = AgentEventBridge()
    bridge.attach_run(run)
    translator = FeishuInputTranslator(bridge=bridge)

    translator.ingest(FeishuInputEvent(kind="button", text="__route__:image_post"))
    translator.ingest(FeishuInputEvent(kind="form", text='__FORM__:{"flatlay":true}'))

    assert run.enqueued == [
        ("__route__:image_post", "asap"),
        ('__FORM__:{"flatlay":true}', "asap"),
    ]


def test_feishu_new_session_control_resets_agent_session() -> None:
    run = FakeAgentRun()
    bridge = AgentEventBridge()
    bridge.attach_run(run)
    bridge.ingest_user_text("旧消息", priority="when_idle")
    translator = FeishuInputTranslator(bridge=bridge)

    translator.ingest(FeishuInputEvent(kind="control", action="new_session"))

    assert run.reset_calls == 1


def test_feishu_rewritten_control_text_resets_agent_session() -> None:
    for text in [
        "__control__:new_session",
        "control:new_session",
        "@__control__:new_session",
        "新开会话",
        "重置会话",
        "/new",
    ]:
        run = FakeAgentRun()
        bridge = AgentEventBridge()
        bridge.attach_run(run)
        translator = FeishuInputTranslator(bridge=bridge)

        translator.ingest(FeishuInputEvent(kind="control", text=text))

        assert run.reset_calls == 1


def test_feishu_follow_up_control_defaults_to_when_idle_queue() -> None:
    run = FakeAgentRun()
    bridge = AgentEventBridge()
    bridge.attach_run(run)
    translator = FeishuInputTranslator(bridge=bridge)

    translator.ingest(FeishuInputEvent(kind="control", action="follow_up"))

    assert run.enqueued == [("[用户控制事件]\naction: follow_up", "when_idle")]
