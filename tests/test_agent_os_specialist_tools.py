from __future__ import annotations

import pytest

from src.agent_os.schemas import ImageRunOptionsSpec, RunOptions, TaskRunSpec
from src.agent_os.specialist_tools import (
    build_route_tool_registry,
    conversation_request_from_task_spec,
)
from src.agent_os.tools import AgentToolContext
from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.run_options import ImagePostRunOptions
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeRouteRunner:
    def __init__(self, route: str) -> None:
        self.route = route
        self.calls = []

    async def run(self, request, **kwargs):
        self.calls.append({"request": request, "kwargs": kwargs})
        return ResultEnvelope[DeliveryPackage].success(
            agent_name=f"{self.route}_runner",
            payload=DeliveryPackage(
                route=self.route,
                title=request.topic,
                summary="done",
            ),
            summary="done",
            run_id=kwargs["run_id"],
            step_id="delivery",
        )


def test_conversation_request_from_task_spec_preserves_runtime_requirements() -> None:
    spec = TaskRunSpec(
        objective="做留学图文",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        audience="准留学生",
        style_constraints=["末日废土风格"],
        run_options=RunOptions(image=ImageRunOptionsSpec(count=10, concurrency=2)),
    )

    request = conversation_request_from_task_spec(spec)

    assert isinstance(request, ConversationRequest)
    assert request.topic == "出国留学"
    assert request.audience == "准留学生"
    assert request.style_constraints == ["末日废土风格"]
    assert request.image_count == 10


@pytest.mark.anyio
async def test_route_tool_registry_executes_image_route_with_spec_params() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="做留学图文",
        route=ContentRoute.IMAGE_POST,
        topic="出国留学",
        audience="准留学生",
        style_constraints=["末日废土风格"],
        run_options=RunOptions(image=ImageRunOptionsSpec(count=10, concurrency=2)),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    assert result.envelope.payload is not None
    assert result.envelope.payload.route == "image_post"
    assert image_runner.calls[0]["request"].image_count == 10
    assert image_runner.calls[0]["kwargs"]["send_to_feishu"] is True
    assert image_runner.calls[0]["kwargs"]["chat_id"] == "chat-1"


@pytest.mark.anyio
async def test_route_tool_tolerates_agent_extra_context_params() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec={"objective": "面试穿搭 5 图", "style_constraints": ["纯色背景"]},
        skill="pure-color-single-look-image-post",
        prompt_template="fashion_flatlay",
    )

    assert result.envelope.status == "success"
    assert image_runner.calls[0]["request"].topic == "面试穿搭 5 图"


@pytest.mark.anyio
async def test_route_tool_adapts_agent_os_run_options_to_image_route_options() -> None:
    image_runner = FakeRouteRunner("image_post")
    registry = build_route_tool_registry(image_runner=image_runner)
    spec = TaskRunSpec(
        objective="做面试通勤穿搭图",
        route=ContentRoute.IMAGE_POST,
        topic="面试通勤穿搭",
        run_options=RunOptions(
            image=ImageRunOptionsSpec(count=5, concurrency=2, size="2K", aspect_ratio="3:4")
        ),
    )

    result = await registry.execute(
        "execute_image_post",
        AgentToolContext(run_id="run-1", chat_id="chat-1"),
        spec=spec.model_dump(mode="json"),
    )

    route_options = image_runner.calls[0]["kwargs"]["run_options"]
    assert result.envelope.status == "success"
    assert isinstance(route_options, ImagePostRunOptions)
    assert route_options.image_generation_concurrency == 2
    assert route_options.image.image_size == "2K"
    assert route_options.image.aspect_ratio == "3:4"
