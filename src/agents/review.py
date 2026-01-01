"""
内容审核 Agent
验证内容质量和一致性（Reflexion 模式）
"""
import os
from pydantic_ai import Agent
from ..models.schemas import ResearchResult, XHSContent, ReviewResult
from prompts import get_system_prompt, get_user_prompt


class ReviewAgent:
    """小红书内容审核 Agent"""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        """
        初始化审核 Agent

        Args:
            model: 使用的模型名称
        """
        # 从环境变量获取 API Key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        self.agent = Agent(
            model=model,
            output_type=ReviewResult,
            instrument=True,  # 启用 Logfire 可观测性
            system_prompt=(get_system_prompt("review"),),  # 从 YAML 加载
        )

    async def review(
        self,
        content: XHSContent,
        research: ResearchResult
    ) -> ReviewResult:
        """
        审核内容质量

        Args:
            content: 待审核的小红书内容
            research: 研究数据（作为审核依据）

        Returns:
            ReviewResult: 审核结果
        """
        # 从 YAML 加载并渲染 user prompt
        prompt = get_user_prompt(
            "review",
            content=content.model_dump_json(indent=2),
            research=research.model_dump_json(indent=2)
        )

        print("   🔍 开始审核内容...")
        result = await self.agent.run(prompt)

        return result.output

    def format_report(self, result: ReviewResult) -> str:
        """
        格式化审核报告

        Args:
            result: 审核结果

        Returns:
            格式化的报告字符串
        """
        lines = []

        # 标题
        status = "✅ 通过" if result.passed else "❌ 未通过"
        lines.append(f"审核结果: {status} (得分: {result.score:.1f}/100)")
        lines.append("")

        # 总结
        lines.append(f"📝 总结: {result.summary}")
        lines.append("")

        # 实体使用情况
        if result.entity_usage:
            lines.append("📊 数据利用率:")
            eu = result.entity_usage
            if "research_entities" in eu and "used_entities" in eu:
                lines.append(f"   - 研究数据实体: {eu['research_entities']} 个")
                lines.append(f"   - 已使用实体: {eu['used_entities']} 个")
                if "usage_rate" in eu:
                    lines.append(f"   - 利用率: {eu['usage_rate']*100:.1f}%")
            lines.append("")

        # 问题列表
        if result.issues:
            lines.append("⚠️  发现的问题:")
            for i, issue in enumerate(result.issues, 1):
                severity_icon = {
                    "critical": "🔴",
                    "warning": "🟡",
                    "info": "🔵"
                }.get(issue.severity, "⚪")

                lines.append(f"   {i}. [{severity_icon} {issue.severity.upper()}] {issue.type}")
                lines.append(f"      问题: {issue.description}")
                lines.append(f"      建议: {issue.suggestion}")
                lines.append("")
        else:
            lines.append("✨ 未发现问题")

        return "\n".join(lines)
