"""Full workflow orchestration."""
from ..utils.logger import get_logger
from .types import WorkflowContext
from ..slices.content import workflow as content_workflow
from ..slices.image import workflow as image_workflow
from ..slices.publish import workflow as publish_workflow
from ..slices.research import workflow as research_workflow

logger = get_logger(__name__)


class FullWorkflow:
    async def run(self, ctx: WorkflowContext) -> WorkflowContext:
        logger.info("=" * 60)
        logger.info("小红书内容创作工作流（Pydantic-AI）")
        logger.info("=" * 60)
        logger.info("主题: %s", ctx.topic)
        logger.info("受众: %s", ctx.audience)
        logger.info("输出目录: %s", ctx.output_dir)

        ctx = await research_workflow.run(ctx)
        ctx = await content_workflow.run(ctx)
        ctx = await image_workflow.run(ctx)
        ctx = await publish_workflow.run(ctx)
        return ctx
