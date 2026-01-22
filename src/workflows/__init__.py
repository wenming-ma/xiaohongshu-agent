"""Full workflow orchestration."""
from ..utils.file_ops import save_json
from ..utils.logger import get_logger
from ..models.schemas import ImageResult
from .types import WorkflowContext
from ..slices.content_agent import workflow as content_workflow
from ..slices.image_agent import workflow as image_workflow
from ..slices.image_agent.agent import ImageAgent
from ..slices.publish_agent import workflow as publish_workflow
from ..slices.research_agent import workflow as research_workflow

logger = get_logger(__name__)


class FullWorkflow:
    async def run(self, ctx: WorkflowContext) -> WorkflowContext:
        logger.info("=" * 60)
        logger.info("小红书内容创作工作流（Pydantic-AI）")
        logger.info("=" * 60)
        logger.info("主题: %s", ctx.topic)
        logger.info("受众: %s", ctx.audience)
        logger.info("输出目录: %s", ctx.output_dir)

        # Phase 1: Research
        ctx = await research_workflow.run(ctx)

        # Phase 2: Content
        ctx = await content_workflow.run(ctx)

        # Phase 3: Image
        if ctx.generate_image:
            ctx = await image_workflow.run(ctx)

        # Phase 4: Publish
        ctx = await publish_workflow.run(ctx)

        return ctx
