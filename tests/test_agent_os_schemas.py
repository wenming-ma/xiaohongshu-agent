from __future__ import annotations

from src.agent_os.schemas import (
    AgentOSEvent,
    DeliverySpec,
    ImageRunOptionsSpec,
    ResearchRunOptionsSpec,
    RunOptions,
    TaskRunSpec,
    TaskStepSpec,
)
from src.orchestration.conversation import ContentRoute


def test_agent_os_event_defaults_to_asap_text_event() -> None:
    event = AgentOSEvent.text("帮我做 5 张图")

    assert event.source == "feishu"
    assert event.kind == "text"
    assert event.text == "帮我做 5 张图"
    assert event.priority == "asap"
    assert event.event_id
    assert event.created_at.tzinfo is not None


def test_task_run_spec_preserves_user_runtime_overrides() -> None:
    spec = TaskRunSpec(
        objective="做出国留学图文帖",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        style_constraints=["末日废土风格", "每张图片都必须有人物"],
        run_options=RunOptions(
            research=ResearchRunOptionsSpec(max_items=5, depth="fast"),
            image=ImageRunOptionsSpec(
                count=10,
                model="gemini-3-pro-image-preview",
                concurrency=2,
            ),
        ),
        steps=[
            TaskStepSpec(
                step_id="research",
                tool_name="run_research",
                params={"topic": "出国留学"},
            )
        ],
    )

    dumped = spec.model_dump(mode="json")

    assert dumped["run_options"]["research"]["max_items"] == 5
    assert dumped["run_options"]["image"]["count"] == 10
    assert dumped["run_options"]["image"]["model"] == "gemini-3-pro-image-preview"
    assert dumped["steps"][0]["tool_name"] == "run_research"


def test_task_run_spec_defaults_to_feishu_delivery() -> None:
    spec = TaskRunSpec(objective="自主探索")

    assert isinstance(spec.delivery, DeliverySpec)
    assert spec.delivery.target == "feishu"
    assert spec.delivery.include_artifacts is True


def test_task_run_spec_accepts_reference_asset_batch_ids_without_extra_schema_fields() -> None:
    spec = TaskRunSpec(
        objective="用已存素材做图文",
        reference_asset_batch_ids=["refbatch_123"],
    )

    dumped = spec.model_dump(mode="json")

    assert dumped["reference_asset_batch_ids"] == ["refbatch_123"]
