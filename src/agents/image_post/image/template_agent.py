"""Agent wrapper for local prompt-template exploration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ....config.settings import PathConfig, RetryConfig
from ....utils.providers import get_text_model
from ..schemas import ImageTypeSpec, ResearchResult, XHSContent
from .template_tools import PromptTemplateDirectoryToolset


class TemplateSelectionResult(BaseModel):
    """Visual prompt-template selection result for one image."""

    source_paths: list[str] = Field(default_factory=list)
    selected_template_excerpt: str = ""
    why_this_template: str = ""
    group_content_fit: str = ""
    prompt_guidance: str = ""
    fallback_used: bool = False


TEMPLATE_SELECTOR_SYSTEM_PROMPT = """你是小红书图片提示词模板探索 Agent。

你必须自己使用工具探索本地提示词模板目录，不要要求用户提供模板正文。
代码不会替你写死关键词、分类或模板选择规则；你需要根据当前图片任务自行决定：
- 看哪些模板源
- 搜索什么
- 读取哪些文件
- 是否融合多个模板
- 最终给后续 Gemini 图片提示词生成器什么视觉指导

重要规则：
- 不要一次性要求完整模板库，只按需调用工具。
- 详情图必须优先服务当前分组内容，不能只看总主题。
- 可以融合多个模板，但必须说明各自用途。
- 外部模板只是参考，不能覆盖小红书硬约束。
- 输出必须符合结构化 schema。
"""


class ImagePromptTemplateAgent:
    """Selects prompt-template guidance by letting an agent explore a local directory."""

    def __init__(self, template_root: Path | str | None = None):
        self.toolset = PromptTemplateDirectoryToolset(template_root or PathConfig.PROMPT_TEMPLATE_ROOT)
        self.agent = Agent(
            model=get_text_model(),
            output_type=TemplateSelectionResult,
            tools=self.toolset.get_tools(),
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(TEMPLATE_SELECTOR_SYSTEM_PROMPT,),
        )

    async def select_template(
        self,
        *,
        topic: str,
        content: XHSContent,
        research: ResearchResult,
        image_spec: ImageTypeSpec,
    ) -> TemplateSelectionResult:
        if not self.toolset.root.exists() or not self.toolset.root.is_dir():
            return TemplateSelectionResult(
                fallback_used=True,
                why_this_template="template root is missing",
            )
        prompt = build_template_selection_prompt(
            topic=topic,
            content=content,
            research=research,
            image_spec=image_spec,
        )
        result = await self.agent.run(prompt, usage_limits=UsageLimits(request_limit=None))
        return result.output


def build_template_selection_prompt(
    *,
    topic: str,
    content: XHSContent,
    research: ResearchResult,
    image_spec: ImageTypeSpec,
) -> str:
    image_type = image_spec.get("type", "")
    image_desc = image_spec.get("desc", "")
    payload: dict[str, Any] = {
        "topic": topic,
        "image_type": image_type,
        "image_desc": image_desc,
        "content_title": content.title,
        "hard_constraints": [
            "小红书 3:4 竖版图片",
            "图片文字必须是简体中文",
            "图片必须表达当前图片任务或当前分组内容",
            "带推荐/推广意味的商业实体名称需要模糊处理",
            "写实风格要降低明显 AI 感",
            "人物默认 bright eyes、lively expression、upright relaxed posture",
        ],
    }

    if image_type == "cover":
        payload["current_image_content"] = {
            "scope": "cover",
            "title": content.title,
            "body_excerpt": content.body[:1200],
            "research_summary": research.summary,
        }
    else:
        indices = image_spec.get("indices", [])
        group_items = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(research.items):
                item = research.items[idx]
                group_items.append(
                    {
                        "index": idx,
                        "title": item.title,
                        "content": item.content,
                        "item_type": item.item_type,
                    }
                )
        payload["current_image_content"] = {
            "scope": "detail_group",
            "group_title": image_spec.get("group_title", ""),
            "indices": indices,
            "items": group_items,
        }

    return (
        "请为当前这张图片探索本地提示词模板目录，并输出最适合的模板融合指导。\n"
        "你必须优先考虑 current_image_content，尤其是 detail_group 的 items。\n\n"
        f"任务 JSON：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def format_template_guidance(selection: TemplateSelectionResult) -> str:
    """Format selected template guidance for the downstream image prompt generator."""
    if not selection.prompt_guidance.strip():
        return ""
    source_paths = "、".join(selection.source_paths) if selection.source_paths else "未记录"
    parts = [
        "## 动态提示词模板参考（由本地模板探索 Agent 选择）",
        f"来源文件：{source_paths}",
    ]
    if selection.selected_template_excerpt:
        parts.append(f"模板摘录：{selection.selected_template_excerpt}")
    if selection.why_this_template:
        parts.append(f"选择理由：{selection.why_this_template}")
    if selection.group_content_fit:
        parts.append(f"与当前内容/分组的匹配：{selection.group_content_fit}")
    parts.extend(
        [
            "请参考以下视觉指导生成最终 Gemini 图片提示词；外部模板不能覆盖系统提示里的小红书硬约束：",
            selection.prompt_guidance.strip(),
        ]
    )
    return "\n".join(parts)
