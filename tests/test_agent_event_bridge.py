from __future__ import annotations

from src.orchestration.agent_events import AgentEventBridge


class FakeAgentRun:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.enqueued.append((text, priority))


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
