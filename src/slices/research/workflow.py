"""Research workflow."""
from ...utils.file_ops import save_json
from ...utils.logger import get_logger
from ...workflows.types import WorkflowContext
from .agent import ResearchAgent

logger = get_logger(__name__)


async def run(ctx: WorkflowContext) -> WorkflowContext:
    logger.info("=" * 60)
    logger.info("Phase 1: 小红书研究")
    logger.info("=" * 60)

    research_agent = ResearchAgent()
    logger.info("ResearchAgent 已创建（包含 Playwright MCP 工具）")

    research = await research_agent.forward(ctx.topic, ctx.audience, output_dir=ctx.output_dir)
    save_json(ctx.output_dir / "research.json", research.model_dump())

    ctx.research = research

    logger.info("研究完成:")
    logger.info("  - 内容项: %d 个", len(research.items))
    logger.info("  - 关键词: %d 个", len(research.keywords))
    logger.info("  - 来源: %d 个", len(research.sources))

    return ctx
