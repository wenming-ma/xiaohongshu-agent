"""Publish workflow."""
from datetime import datetime
from pathlib import Path

from ...models.schemas import PublishResult
from ...utils.file_ops import save_json
from ...utils.logger import get_logger
from ...workflows.types import WorkflowContext
from .agent import PublisherAgent

logger = get_logger(__name__)


async def run(ctx: WorkflowContext) -> WorkflowContext:
    if not ctx.publish:
        logger.info("跳过发布（publish=False）")
        return ctx

    if ctx.image_result is None:
        logger.info("跳过发布：缺少 image_result")
        return ctx

    if ctx.content is None:
        raise ValueError("PublishWorkflow requires ctx.content")

    logger.info("=" * 60)
    logger.info("Phase 4: 发布到小红书")
    logger.info("=" * 60)

    image_paths = [Path(img.image_path) for img in ctx.image_result.images]

    try:
        publisher_agent = PublisherAgent()
        logger.info("PublisherAgent 已创建（包含 Playwright MCP 工具）")

        publish_result = await publisher_agent.forward(
            content=ctx.content,
            images=image_paths,
            output_dir=ctx.output_dir,
        )

        save_json(ctx.output_dir / "publish.json", publish_result.model_dump())
        ctx.publish_result = publish_result

        if publish_result.published:
            logger.info("发布成功:")
            logger.info("  - 发布时间: %s", publish_result.publish_time)
            if publish_result.post_url:
                logger.info("  - 链接: %s", publish_result.post_url)
            if publish_result.retry_count > 0:
                logger.info("  - 重试次数: %d", publish_result.retry_count)
        else:
            logger.error("发布失败:")
            logger.error("  - 错误: %s", publish_result.error_message)
            logger.error("  - 元数据已保存到 publish.json，可手动重试")
    except Exception as exc:
        logger.warning("发布失败: %s", exc)
        failed_result = PublishResult(
            published=False,
            publish_time=datetime.now().isoformat(),
            error_message=str(exc),
            content_snapshot=ctx.content.model_dump(),
            image_paths=[str(p) for p in image_paths],
        )
        save_json(ctx.output_dir / "publish.json", failed_result.model_dump())
        ctx.publish_result = failed_result

    return ctx
