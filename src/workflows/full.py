"""Full workflow orchestration."""
from ..utils.logger import get_logger
from .content import ContentWorkflow
from .image import ImageWorkflow
from .publish import PublishWorkflow
from .research import ResearchWorkflow
from .types import WorkflowContext

logger = get_logger(__name__)


class FullWorkflow:
    async def run(self, ctx: WorkflowContext) -> WorkflowContext:
        logger.info("=" * 60)
        logger.info("小红书内容创作工作流（Pydantic-AI）")
        logger.info("=" * 60)
        logger.info("主题: %s", ctx.topic)
        logger.info("受众: %s", ctx.audience)
        logger.info("输出目录: %s", ctx.output_dir)

        ctx = await ResearchWorkflow().run(ctx)
        ctx = await ContentWorkflow().run(ctx)
        ctx = await ImageWorkflow().run(ctx)
        ctx = await PublishWorkflow().run(ctx)
        return ctx
