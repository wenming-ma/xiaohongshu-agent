"""Research workflow."""
from ..utils.file_ops import save_json
from ..utils.logger import get_logger
from ..slices.research.agent import ResearchAgent
from .types import WorkflowContext

logger = get_logger(__name__)


class ResearchWorkflow:
    async def run(self, ctx: WorkflowContext) -> WorkflowContext:
        logger.info("=" * 60)
        logger.info("Phase 1: 小红书研究")
        logger.info("=" * 60)

        research_agent = ResearchAgent()
        logger.info("ResearchAgent 已创建（包含 Playwright MCP 工具）")

        research = await research_agent.research(ctx.topic, ctx.audience, output_dir=ctx.output_dir)
        save_json(ctx.output_dir / "research.json", research.model_dump())

        ctx.research = research

        logger.info("研究完成:")
        logger.info("  - 关键信息: %d 个", len(research.key_infos))
        logger.info("  - 案例: %d 个", len(research.cases))
        logger.info("  - 关键词: %d 个", len(research.keywords))
        logger.info("  - 可信度: %s", research.credibility)
        logger.info("  - 数据点: %d 个", research.data_points)

        return ctx
