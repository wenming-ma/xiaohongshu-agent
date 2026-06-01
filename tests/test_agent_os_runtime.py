from __future__ import annotations

from pathlib import Path

from src.agent_os.runtime import MainAgentRuntime
from src.agent_os.schemas import AgentOSEvent


class FakeAgentRun:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []
        self.reset_calls = 0
        self.cancel_calls = 0
        self.idle_waits = 0

    def enqueue(self, text: str, *, priority: str = "asap") -> None:
        self.enqueued.append((text, priority))

    def reset_session(self) -> None:
        self.reset_calls += 1

    def cancel_current_task(self) -> None:
        self.cancel_calls += 1

    async def wait_for_idle(self) -> None:
        self.idle_waits += 1


def test_runtime_buffers_until_agent_run_attaches() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()

    runtime.ingest_event(AgentOSEvent.text("先做 5 张图"))
    runtime.attach_run(run)

    assert run.enqueued == [("先做 5 张图", "asap")]
    assert runtime.pending_count == 0


def test_runtime_formats_image_event_as_user_message(tmp_path: Path) -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()
    runtime.attach_run(run)
    image_path = tmp_path / "ref.jpg"
    image_path.write_bytes(b"img")

    runtime.ingest_event(
        AgentOSEvent.image(str(image_path), caption="参考这件外套", priority="when_idle")
    )

    message, priority = run.enqueued[0]
    assert priority == "when_idle"
    assert "[用户发送图片]" in message
    assert str(image_path) in message
    assert "参考这件外套" in message


def test_runtime_new_session_resets_run_and_clears_pending() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()

    runtime.ingest_event(AgentOSEvent.text("旧任务", priority="when_idle"))
    runtime.ingest_event(AgentOSEvent.control("new_session"))
    runtime.attach_run(run)

    assert runtime.pending_count == 0
    assert run.enqueued == []

    runtime.ingest_event(AgentOSEvent.text("新任务"))
    runtime.ingest_event(AgentOSEvent.control("new_session"))

    assert run.reset_calls == 1


def test_runtime_interrupt_cancels_current_task_and_enqueues_control_message() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()
    runtime.attach_run(run)

    runtime.ingest_event(AgentOSEvent.control("interrupt"))

    assert run.cancel_calls == 1
    assert run.enqueued == [("[用户控制事件]\naction: interrupt", "asap")]


def test_runtime_attach_run_flushes_pending_in_order() -> None:
    runtime = MainAgentRuntime()
    run = FakeAgentRun()

    runtime.ingest_text("第一条")
    runtime.ingest_text("第二条", priority="when_idle")
    runtime.attach_run(run)

    assert run.enqueued == [("第一条", "asap"), ("第二条", "when_idle")]
