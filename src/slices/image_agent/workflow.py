"""Image workflow."""
from ...utils.file_ops import save_json
from ...utils.logger import get_logger
from ...workflows.types import WorkflowContext
from .agent import ImageAgent

logger = get_logger(__name__)


async def run(ctx: WorkflowContext) -> WorkflowContext:
    if not ctx.generate_image:
        logger.info("跳过配图生成（generate_image=False）")
        return ctx

    if ctx.content is None or ctx.research is None:
        raise ValueError("ImageWorkflow requires ctx.content and ctx.research")

    logger.info("=" * 60)
    logger.info("Phase 3: 配图生成")
    logger.info("=" * 60)

    try:
        image_agent = ImageAgent()
        logger.info("ImageAgent 已创建（包含 Playwright MCP 工具）")

        image_result = await image_agent.forward(
            content=ctx.content,
            research=ctx.research,
            topic=ctx.topic,
            output_dir=ctx.output_dir,
        )

        save_json(ctx.output_dir / "image.json", image_result.model_dump())
        ctx.image_result = image_result

        logger.info("配图生成完成:")
        logger.info("  - 生成数量: %d 张", image_result.total_count)
        for img in image_result.images:
            logger.info("  - %s: %s", img.image_type, img.image_path)
        logger.info("  - 生成时间: %s", image_result.generated_at)
    except Exception:
        logger.exception("配图生成失败")
        logger.warning("继续完成其他步骤...")
        ctx.image_result = None

    return ctx
