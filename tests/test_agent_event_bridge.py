from __future__ import annotations

from pathlib import Path

from src.orchestration.agent_events import AgentEventBridge


class FakeAgentRun:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []
        self.reset_calls = 0

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.enqueued.append((text, priority))

    def reset_session(self) -> None:
        self.reset_calls += 1


def test_event_bridge_buffers_until_agent_run_is_attached() -> None:
    bridge = AgentEventBridge()
    run = FakeAgentRun()

    bridge.ingest_user_text("换成纯色背景")
    bridge.attach_run(run)

    assert run.enqueued == [("换成纯色背景", "asap")]


def test_event_bridge_injects_into_active_agent_run() -> None:
    bridge = AgentEventBridge()
    run = FakeAgentRun()

    bridge.attach_run(run)
    bridge.ingest_user_text("当前任务做完后，再加两张图", priority="when_idle")

    assert run.enqueued == [("当前任务做完后，再加两张图", "when_idle")]


def test_event_bridge_translates_images_into_plain_user_messages(tmp_path: Path) -> None:
    bridge = AgentEventBridge()
    run = FakeAgentRun()
    image_path = tmp_path / "reference.jpg"
    image_path.write_bytes(b"image")

    bridge.attach_run(run)
    bridge.ingest_user_image(image_path, caption="参考这套衣服", priority="when_idle")

    assert len(run.enqueued) == 1
    message, priority = run.enqueued[0]
    assert priority == "when_idle"
    assert "[用户发送图片]" in message
    assert str(image_path) in message
    assert "参考这套衣服" in message


def test_event_bridge_new_session_control_clears_pending_and_resets_run() -> None:
    bridge = AgentEventBridge()
    run = FakeAgentRun()

    bridge.ingest_user_text("旧需求", priority="when_idle")
    bridge.ingest_control_action("new_session")

    assert bridge.pending_count == 0

    bridge.attach_run(run)
    bridge.ingest_user_text("新需求")
    bridge.ingest_control_action("new_session")

    assert run.reset_calls == 1
