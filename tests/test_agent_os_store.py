from __future__ import annotations

from src.agent_os.schemas import AgentOSEvent, TaskRunSpec
from src.agent_os.store import AgentOSStore
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


def test_store_appends_events_and_reads_them_back(tmp_path) -> None:
    store = AgentOSStore(tmp_path)
    event = AgentOSEvent.text("做 3 张图")

    store.append_event(event)

    events = store.read_events()
    assert len(events) == 1
    assert events[0].text == "做 3 张图"


def test_store_saves_task_spec_and_envelope(tmp_path) -> None:
    store = AgentOSStore(tmp_path)
    spec = TaskRunSpec(task_id="task-1", objective="做图文")
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery_agent",
        payload=DeliveryPackage(route="image_post", title="标题", summary="done"),
        summary="done",
        run_id="run-1",
        step_id="delivery",
    )

    store.save_task_spec(spec)
    store.save_envelope("task-1", "delivery", envelope)

    assert store.read_task_spec("task-1").objective == "做图文"
    assert store.read_envelope("task-1", "delivery").payload["title"] == "标题"
