from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from src.config.settings import RetryConfig
from src.utils.providers import get_text_model

from .conversation import ContentRoute, ConversationRequest
from .skills import SkillSpec


class PlanningDecision(BaseModel):
    route: ContentRoute = Field(description="Best content route for this request.")
    selected_skill_names: list[str] = Field(
        default_factory=list,
        description="Names of project Skill Protocol documents that should guide the workflow.",
    )
    rationale: str = Field(default="", description="Short reason for the route and skill choices.")


PLANNING_SYSTEM_PROMPT = """你是飞书优先内容系统的主规划 Agent。

你的职责是根据用户当前需求，选择内容路线和需要加载的 Skill。
所有选择都必须基于语义理解和任务目标，不要按固定关键词表、文件名规则或硬编码分类来触发。

架构准则：
- 每个专项 Agent 只负责一类通用任务；你只做规划，不替专项 Agent 执行任务。
- Skill 是经验、流程、提示词和检查清单，不是运行时 schema。
- 如果用户明确点选了路线，通常应尊重用户选择；除非用户文本明显矛盾，才在 rationale 中说明。
- 只从 available_skills 中选择 Skill；不要编造不存在的 Skill 名称。
- 输出必须符合结构化 schema。
"""


class PlanningAgent:
    """Agent-driven route and Skill selector for Feishu content orchestration."""

    def __init__(self) -> None:
        self.agent = Agent(
            model=get_text_model(),
            output_type=PlanningDecision,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(PLANNING_SYSTEM_PROMPT,),
        )

    async def decide(
        self,
        request: ConversationRequest,
        *,
        available_skills: Sequence[SkillSpec],
    ) -> PlanningDecision:
        prompt = build_planning_prompt(request, available_skills=available_skills)
        result = await self.agent.run(prompt)
        return result.output


def build_planning_prompt(
    request: ConversationRequest,
    *,
    available_skills: Sequence[SkillSpec],
) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "available_routes": [route.value for route in ContentRoute],
        "available_skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "body_excerpt": skill.body[:1200],
            }
            for skill in available_skills
        ],
    }
    return (
        "请根据下面 JSON 规划这次飞书内容工作流。\n"
        "不要使用关键词触发规则；请基于用户目标、风格约束、内容形态和可用 Skill 的语义匹配做选择。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
