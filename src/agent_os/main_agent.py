from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from src.utils.providers import get_text_model

from .schemas import AgentToolResult
from .tools import AgentToolContext, AgentToolRegistry


MAIN_AGENT_SYSTEM_PROMPT = """你是飞书内容系统的主 Agent，是一个长期运行的任务规划和组织者。

你的职责：
- 理解用户随时发来的自然语言、图片、按钮和表单反馈。
- 把用户要求转成明确的 TaskRunSpec 和工具调用参数。
- 选择 Skill、提示词模板和专项 Agent 工具。
- 通过工具询问用户、执行任务、读取产物、发送飞书交付。

边界：
- 不要亲自执行专项任务；研究、分组、图片生成、文章、视频、登录、交付都通过工具调用完成。
- 不要要求用户使用固定格式。缺信息时用飞书工具让用户点选或补充。
- 不要使用关键词触发规则选择 Skill 或提示词模板；根据语义和任务目标选择。
- 用户指定的数量、风格、模型、参考图、研究深度、并发、审核严格度必须变成工具参数。
- 最终内容只交付到飞书。
"""


class MainAgentDependencies(BaseModel):
    tool_registry: AgentToolRegistry = Field(default_factory=AgentToolRegistry)
    session_id: str | None = None
    chat_id: str | None = None

    model_config = {"arbitrary_types_allowed": True}


def create_main_agent() -> Agent[MainAgentDependencies, str]:
    agent = Agent(
        model=get_text_model(),
        deps_type=MainAgentDependencies,
        output_type=str,
        system_prompt=(MAIN_AGENT_SYSTEM_PROMPT,),
        instrument=True,
    )

    @agent.tool
    async def describe_available_tools(
        ctx: RunContext[MainAgentDependencies],
    ) -> list[dict[str, str]]:
        return ctx.deps.tool_registry.describe_tools()

    @agent.tool
    async def execute_agent_tool(
        ctx: RunContext[MainAgentDependencies],
        tool_name: str,
        params: dict[str, Any],
        run_id: str,
        task_id: str | None = None,
        step_id: str | None = None,
    ) -> AgentToolResult:
        tool_ctx = AgentToolContext(
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
            chat_id=ctx.deps.chat_id,
        )
        return await ctx.deps.tool_registry.execute(tool_name, tool_ctx, **params)

    return agent
