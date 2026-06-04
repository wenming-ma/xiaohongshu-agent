from __future__ import annotations

import pytest

from src.agent_os.main_agent import (
    MAIN_AGENT_SYSTEM_PROMPT,
    MainAgentDependencies,
    create_main_agent,
    execute_main_agent_registry_tool,
)
from src.agent_os.schemas import AgentToolResult
from src.agent_os.tools import AgentTool, AgentToolContext, AgentToolRegistry
from src.orchestration.schemas import ResultEnvelope


def test_main_agent_prompt_defines_planner_not_worker_role() -> None:
    assert "任务规划和组织者" in MAIN_AGENT_SYSTEM_PROMPT
    assert "长期运行" in MAIN_AGENT_SYSTEM_PROMPT
    assert "不要亲自执行专项任务" in MAIN_AGENT_SYSTEM_PROMPT
    assert "后台任务" in MAIN_AGENT_SYSTEM_PROMPT
    assert "并发" in MAIN_AGENT_SYSTEM_PROMPT
    assert "状态" in MAIN_AGENT_SYSTEM_PROMPT
    assert "重启" in MAIN_AGENT_SYSTEM_PROMPT
    assert "schedule_background_agent_task" in MAIN_AGENT_SYSTEM_PROMPT
    assert "周期" in MAIN_AGENT_SYSTEM_PROMPT
    assert "category=specialist" in MAIN_AGENT_SYSTEM_PROMPT
    assert "多轮对话" in MAIN_AGENT_SYSTEM_PROMPT
    assert "TaskRunSpec" in MAIN_AGENT_SYSTEM_PROMPT
    assert "WorkflowInvocation" in MAIN_AGENT_SYSTEM_PROMPT
    assert "ImagePlanner" in MAIN_AGENT_SYSTEM_PROMPT
    assert "不要规划每张图片" in MAIN_AGENT_SYSTEM_PROMPT
    assert "飞书" in MAIN_AGENT_SYSTEM_PROMPT
    assert "feishu_" in MAIN_AGENT_SYSTEM_PROMPT
    assert "本地文件" in MAIN_AGENT_SYSTEM_PROMPT
    assert "文件夹路径" in MAIN_AGENT_SYSTEM_PROMPT
    assert "agent-os-conversation-planning" in MAIN_AGENT_SYSTEM_PROMPT
    assert "read_skill" in MAIN_AGENT_SYSTEM_PROMPT


def test_main_agent_dependencies_hold_tool_registry() -> None:
    registry = AgentToolRegistry()
    deps = MainAgentDependencies(tool_registry=registry)

    assert deps.tool_registry is registry


def test_create_main_agent_returns_agent_with_expected_tools() -> None:
    agent = create_main_agent()
    tool_names = {
        tool.name
        for toolset in agent.toolsets
        for tool in toolset.tools.values()
    }

    assert "describe_available_tools" in tool_names
    assert "execute_agent_tool" in tool_names


async def _fake_specialist(ctx: AgentToolContext, **params) -> AgentToolResult:
    return AgentToolResult(
        envelope=ResultEnvelope[dict].success(
            agent_name="fake_specialist",
            payload={"ran": True},
            summary="ran",
            run_id=ctx.run_id,
            step_id="fake",
        )
    )


async def _fake_task_tool(ctx: AgentToolContext, **params) -> AgentToolResult:
    return AgentToolResult(
        envelope=ResultEnvelope[dict].success(
            agent_name="fake_task_tool",
            payload={"params": params},
            summary="started",
            run_id=ctx.run_id,
            step_id="task",
        )
    )


@pytest.mark.anyio
async def test_main_agent_blocks_direct_specialist_execution() -> None:
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="execute_image_post",
            description="Image specialist",
            execute=_fake_specialist,
            category="specialist",
        )
    )
    deps = MainAgentDependencies(tool_registry=registry)

    result = await execute_main_agent_registry_tool(
        deps,
        tool_name="execute_image_post",
        params={"spec": {"objective": "test"}},
        run_id="run-direct-specialist",
    )

    assert result.envelope.status == "error"
    assert "cannot run inside the main chat loop" in (result.envelope.error_message or "")
    assert result.next_suggestions


@pytest.mark.anyio
async def test_main_agent_allows_task_tools_to_start_specialists() -> None:
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="start_background_agent_task",
            description="Start specialist in background",
            execute=_fake_task_tool,
            category="task",
        )
    )
    deps = MainAgentDependencies(tool_registry=registry)

    result = await execute_main_agent_registry_tool(
        deps,
        tool_name="start_background_agent_task",
        params={"tool_name": "execute_image_post", "params": {"topic": "通勤"}},
        run_id="run-background",
    )

    assert result.envelope.status == "success"
    assert result.envelope.payload == {
        "params": {"tool_name": "execute_image_post", "params": {"topic": "通勤"}}
    }
