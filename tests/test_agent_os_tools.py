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


@pytest.mark.anyio
async def test_registry_allows_tool_params_named_name() -> None:
    async def echo_name(ctx: AgentToolContext, **params):
        return AgentToolResult(
            envelope=ResultEnvelope[dict].success(
                agent_name="echo",
                payload={"name": params["name"]},
                summary="ok",
                run_id=ctx.run_id,
                step_id="echo",
            )
        )

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="read_skill",
            description="Read by name",
            execute=echo_name,
            category="resource",
        )
    )

    result = await registry.execute(
        "read_skill",
        AgentToolContext(run_id="run-1"),
        name="agent-os-conversation-planning",
    )

    assert result.envelope.payload == {"name": "agent-os-conversation-planning"}


@pytest.mark.anyio
async def test_registry_allows_tool_params_named_tool_name() -> None:
    async def echo_tool_name(ctx: AgentToolContext, **params):
        return AgentToolResult(
            envelope=ResultEnvelope[dict].success(
                agent_name="echo",
                payload={"tool_name": params["tool_name"]},
                summary="ok",
                run_id=ctx.run_id,
                step_id="echo",
            )
        )

    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="start_background_agent_task",
            description="Start a tool by name",
            execute=echo_tool_name,
            category="task",
        )
    )

    result = await registry.execute(
        "start_background_agent_task",
        AgentToolContext(run_id="run-1"),
        tool_name="execute_image_post",
    )

    assert result.envelope.payload == {"tool_name": "execute_image_post"}


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
