"""
内容创作 Agent
基于研究数据生成小红书内容
"""
import os
from pydantic_ai import Agent
from ..models.schemas import ResearchResult, XHSContent
from prompts import get_system_prompt, get_user_prompt


class ContentAgent:
    """小红书内容创作 Agent"""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        """
        初始化内容 Agent

        Args:
            model: 使用的模型名称
        """
        # 从环境变量获取 API Key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        self.agent = Agent(
            model=model,
            output_type=XHSContent,
            instrument=True,  # ✅ 启用 Logfire 可观测性
            system_prompt=(get_system_prompt("content"),),  # ✅ 从 YAML 加载
        )

    async def create_content(
        self,
        research: ResearchResult,
        topic: str
    ) -> XHSContent:
        """
        创作小红书内容

        Args:
            research: 研究结果
            topic: 主题

        Returns:
            XHSContent: 创作的内容
        """
        # 从 YAML 加载并渲染 user prompt
        prompt = get_user_prompt(
            "content",
            topic=topic,
            research_data=research.model_dump_json(indent=2)
        )

        print("   ✍️  开始创作内容...")
        result = await self.agent.run(prompt)

        return result.output
