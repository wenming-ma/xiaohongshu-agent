from __future__ import annotations

import pytest

from src.agent_os.schemas import AgentToolResult
from src.agent_os.tools import AgentTool, AgentToolContext, AgentToolRegistry
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


async def fake_execute(ctx: AgentToolContext, **params):
    assert ctx.run_id == "run-1"
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="fake_tool",
        payload=DeliveryPackage(route="image_post", title=params["title"], summary="ok"),
        summary="ok",
        run_id=ctx.run_id,
        step_id="fake",
    )
    return AgentToolResult(envelope=envelope, produced_refs=["delivery"])


@pytest.mark.anyio
async def test_registry_executes_registered_tool() -> None:
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="fake_delivery",
            description="Fake delivery tool",
            execute=fake_execute,
        )
    )

    result = await registry.execute(
        "fake_delivery",
        AgentToolContext(run_id="run-1"),
        title="测试标题",
    )

    assert result.envelope.payload is not None
    assert result.envelope.payload.title == "测试标题"
    assert result.produced_refs == ["delivery"]


def test_registry_rejects_duplicate_tool_names() -> None:
    registry = AgentToolRegistry()
    tool = AgentTool(name="same", description="one", execute=fake_execute)

    registry.register(tool)

    with pytest.raises(ValueError, match="Duplicate Agent OS tool"):
        registry.register(tool)


def test_registry_lists_tools_without_exposing_callables() -> None:
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="fake_delivery",
            description="Fake delivery tool",
            execute=fake_execute,
        )
    )

    assert registry.describe_tools() == [
        {
            "name": "fake_delivery",
            "description": "Fake delivery tool",
            "category": "specialist",
        }
    ]
