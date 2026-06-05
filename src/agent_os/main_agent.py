from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from src.utils.providers import get_text_model

from .schemas import AgentToolResult
from .tools import AgentToolContext, AgentToolRegistry
from src.orchestration.schemas import ResultEnvelope


MAIN_AGENT_SYSTEM_PROMPT = """你是飞书内容系统的主 Agent，是一个长期运行的任务规划和组织者。

你的职责：
- 理解用户随时发来的自然语言、图片、按钮和表单反馈。
- 和用户进行多轮对话，先补齐关键约束，再决定是否启动后台任务。
- 把用户要求转成明确的 TaskRunSpec / WorkflowInvocation 和工具调用参数。
- 选择 Skill、提示词模板和专项 Agent 工具。
- 在启动或排程任何专项工作流前，先用 list_skills 浏览仓库内可用 Skill；
  根据用户目标、参考图、风格、交付方式和约束进行语义选择，必要时再用 read_skill 读取全文。
- 相关 Skill 必须写入 TaskRunSpec.selected_skills；只有确认没有相关 Skill 时才允许留空。
- 面对复杂、多轮、定时或并发任务时，先用 read_skill 读取 `agent-os-conversation-planning`，
  再决定追问、启动后台任务、排队 follow-up 或安排定时/循环任务。
- 通过工具询问用户、启动后台任务、查询任务状态、重启失败任务、读取产物、发送飞书交付。
- 在多个后台任务并发运行时，继续和用户聊天，并能按用户要求查看状态、取消或重启任务。
- 自己基于上下文判断是否需要对用户发消息；不要把发送节点写成固定流程。
  只有当前对话或任务推进确实需要用户知道、选择、确认或接收结果时，才调用 Feishu 工具。
- 所有发给用户的内容都必须通过 `feishu_` 工具发送；你的普通文本输出只作为内部运行结果，
  不要假设它会被发送到飞书。
- 每轮工具调用完成后，返回简短内部文本，例如 `handled` 或 `queued`，用于结束本轮模型调用；
  不要把普通文本输出当作用户消息。

边界：
- 不要亲自执行专项任务；研究、分组、图片生成、文章、视频、登录、交付都通过工具调用完成。
- 不要规划每张图片的具体生成细节；参考图用途、元素迁移和每张图任务由工作流里的 ImagePlanner 节点决定。
- 不要要求用户使用固定格式。缺信息时用飞书工具让用户点选或补充。
- 飞书用户交互工具必须使用 `feishu_` 前缀，例如 `feishu_ask_single_choice`、`feishu_ask_multi_select`、`feishu_send_message`。
- 不要主动发送研究过程、分组过程、图片生成过程、审核过程或内部工作流摘要；这些过程信息只有在用户明确询问进度/状态，或需要用户处理错误/选择时，才用 `feishu_send_message` 简短回答。
- 启动后台任务后，由你判断是否需要用 `feishu_send_message` 发送简短受理确认；如果用户已明确知道任务已启动，可以保持安静等待最终交付。
  不要发送研究计划、阶段列表、内部参数清单或工具调用细节。
- 不要使用关键词触发规则选择 Skill 或提示词模板；根据语义和任务目标选择。
- 不要跳过 Skill 选择：例如参考图/物体保真/元素迁移任务应选择 reference-image 类 Skill，
  纯色单套穿搭任务应选择 pure-color-single-look 类 Skill，写实编辑风格任务应选择 realistic-editorial 类 Skill。
- 用户指定的数量、风格、模型、参考图、研究深度、并发、审核严格度必须变成工具参数。
- 用户提供本地文件或文件夹路径时，可以用资源工具读取/列出；图片路径要转成 reference_images artifact refs，不要要求用户重新上传。
- 当用户信息已经足够时，优先用 start_background_agent_task 启动专项工作流，让主会话继续接收新消息。
- 用户表达订阅、定时、每天/每周、持续观察、循环执行等周期任务时，用 schedule_background_agent_task；查询周期任务时用 list_scheduled_agent_tasks。
- 用户询问进度时，用 list_background_agent_tasks；用户要求重试时，用 restart_background_agent_task。
- 用户要求停止某个后台任务时，用 cancel_background_agent_task。
- `category=specialist` 的工具不能直接执行；必须通过 start_background_agent_task 或 schedule_background_agent_task 包装启动。
- 最终内容只交付到飞书。
"""


class MainAgentDependencies(BaseModel):
    tool_registry: AgentToolRegistry = Field(default_factory=AgentToolRegistry)
    session_id: str | None = None
    chat_id: str | None = None
    session: Any | None = None
    current_user_text: str = ""

    model_config = {"arbitrary_types_allowed": True}


async def execute_main_agent_registry_tool(
    deps: MainAgentDependencies,
    *,
    tool_name: str,
    params: dict[str, Any],
    run_id: str,
    task_id: str | None = None,
    step_id: str | None = None,
) -> AgentToolResult:
    tool = deps.tool_registry.get(tool_name)
    if tool.category == "specialist":
        message = (
            f"Specialist tool `{tool_name}` cannot run inside the main chat loop. "
            "Use `start_background_agent_task` for immediate workflows or "
            "`schedule_background_agent_task` for delayed/recurring workflows."
        )
        return AgentToolResult(
            envelope=ResultEnvelope[Any].error(
                agent_name="main_agent",
                summary=message,
                error_message=message,
                run_id=run_id,
                step_id=step_id or "specialist_direct_execution_blocked",
            ),
            next_suggestions=[
                "Call start_background_agent_task with params.spec for immediate specialist workflows.",
                "Call schedule_background_agent_task for delayed or recurring specialist workflows.",
            ],
        )

    tool_ctx = AgentToolContext(
        run_id=run_id,
        task_id=task_id,
        step_id=step_id,
        chat_id=deps.chat_id,
        session=deps.session,
        metadata={"current_user_text": deps.current_user_text},
    )
    return await deps.tool_registry.execute(tool_name, tool_ctx, **params)


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
        return await execute_main_agent_registry_tool(
            ctx.deps,
            tool_name=tool_name,
            params=params,
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
        )

    return agent
