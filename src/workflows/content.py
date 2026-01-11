"""Content workflow."""
from ..utils.file_ops import save_json
from ..utils.logger import get_logger
from ..slices.content.agent import ContentAgent
from .types import WorkflowContext

logger = get_logger(__name__)


class ContentWorkflow:
    async def run(self, ctx: WorkflowContext) -> WorkflowContext:
        if ctx.research is None:
            raise ValueError("ContentWorkflow requires ctx.research")

        logger.info("=" * 60)
        logger.info("Phase 2: 内容创作")
        logger.info("=" * 60)

        content_agent = ContentAgent()
        content = await content_agent.create_content(ctx.research, ctx.topic)
        save_json(ctx.output_dir / "content.json", content.model_dump())

        ctx.content = content

        logger.info("内容创作完成:")
        logger.info("  - 标题: %s", content.title)
        logger.info("  - 正文长度: %d 字", len(content.body))
        logger.info("  - 标签: %s", ", ".join(content.hashtags))

        return ctx
