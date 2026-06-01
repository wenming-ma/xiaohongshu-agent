from __future__ import annotations

from src.agent_os.main_agent import (
    MAIN_AGENT_SYSTEM_PROMPT,
    MainAgentDependencies,
    create_main_agent,
)
from src.agent_os.tools import AgentToolRegistry


def test_main_agent_prompt_defines_planner_not_worker_role() -> None:
    assert "任务规划和组织者" in MAIN_AGENT_SYSTEM_PROMPT
    assert "长期运行" in MAIN_AGENT_SYSTEM_PROMPT
    assert "不要亲自执行专项任务" in MAIN_AGENT_SYSTEM_PROMPT
    assert "后台任务" in MAIN_AGENT_SYSTEM_PROMPT
    assert "并发" in MAIN_AGENT_SYSTEM_PROMPT
    assert "状态" in MAIN_AGENT_SYSTEM_PROMPT
    assert "重启" in MAIN_AGENT_SYSTEM_PROMPT
    assert "多轮对话" in MAIN_AGENT_SYSTEM_PROMPT
    assert "TaskRunSpec" in MAIN_AGENT_SYSTEM_PROMPT
    assert "飞书" in MAIN_AGENT_SYSTEM_PROMPT
    assert "feishu_" in MAIN_AGENT_SYSTEM_PROMPT
    assert "本地文件" in MAIN_AGENT_SYSTEM_PROMPT
    assert "文件夹路径" in MAIN_AGENT_SYSTEM_PROMPT


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
