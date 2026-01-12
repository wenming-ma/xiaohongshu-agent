"""Full workflow orchestration."""
import asyncio
from datetime import datetime

from ..utils.file_ops import save_json
from ..utils.logger import get_logger
from ..models.schemas import ImageResult
from .types import WorkflowContext
from ..slices.content import workflow as content_workflow
from ..slices.image import workflow as image_workflow
from ..slices.image.agent import ImageAgent
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

        # Phase 1: Research（必须先完成）
        ctx = await research_workflow.run(ctx)

        # Phase 2: Content + Detail Images 并行
        if ctx.generate_image and ctx.research is not None:
            ctx = await self._run_parallel_content_and_details(ctx)
        else:
            # 不生成图片时，只运行 content
            ctx = await content_workflow.run(ctx)

        # Phase 3: Cover Image（依赖 content）
        if ctx.generate_image and ctx._detail_images:
            ctx = await self._run_cover_image(ctx)

        # Phase 4: Publish
        ctx = await publish_workflow.run(ctx)

        return ctx

    async def _run_parallel_content_and_details(self, ctx: WorkflowContext) -> WorkflowContext:
        """并行执行 content 创作和 detail 图生成"""
        logger.info("=" * 60)
        logger.info("Phase 2: Content + Detail Images（并行执行）")
        logger.info("=" * 60)

        async def run_content():
            """运行 content workflow"""
            return await content_workflow.run(ctx)

        async def run_detail_images():
            """运行 detail 图生成"""
            try:
                image_agent = ImageAgent()
                logger.info("ImageAgent 已创建（Phase 1: detail 图）")

                detail_images, image_types = await image_agent.forward_details_only(
                    research=ctx.research,
                    topic=ctx.topic,
                    output_dir=ctx.output_dir,
                )
                return detail_images, image_types
            except Exception as e:
                logger.exception("Detail 图生成失败: %s", e)
                return [], []

        # 并行执行
        content_task = asyncio.create_task(run_content())
        detail_task = asyncio.create_task(run_detail_images())

        # 等待两个任务完成
        updated_ctx, (detail_images, image_types) = await asyncio.gather(
            content_task, detail_task
        )

        # 更新 context
        ctx.content = updated_ctx.content
        ctx._detail_images = detail_images
        ctx._image_types = image_types

        logger.info("并行阶段完成:")
        logger.info("  - Content: %s", "✓" if ctx.content else "✗")
        logger.info("  - Detail 图: %d 张", len(ctx._detail_images))

        return ctx

    async def _run_cover_image(self, ctx: WorkflowContext) -> WorkflowContext:
        """生成 cover 图（依赖 content）"""
        logger.info("=" * 60)
        logger.info("Phase 3: Cover Image（依赖 content）")
        logger.info("=" * 60)

        if ctx.content is None:
            logger.warning("跳过 cover 图生成：content 为空")
            # 只有 detail 图
            ctx.image_result = ImageResult(
                images=ctx._detail_images,
                total_count=len(ctx._detail_images),
                generated_at=datetime.now().isoformat()
            )
            return ctx

        try:
            image_agent = ImageAgent()
            logger.info("ImageAgent 已创建（Phase 2: cover 图）")

            image_result = await image_agent.forward_cover_only(
                content=ctx.content,
                research=ctx.research,
                topic=ctx.topic,
                output_dir=ctx.output_dir,
                detail_images=ctx._detail_images,
                image_types=ctx._image_types,
            )

            save_json(ctx.output_dir / "image.json", image_result.model_dump())
            ctx.image_result = image_result

            logger.info("配图生成完成:")
            logger.info("  - 生成数量: %d 张", image_result.total_count)
            for img in image_result.images:
                logger.info("  - %s: %s", img.image_type, img.image_path)

        except Exception as e:
            logger.exception("Cover 图生成失败: %s", e)
            # 回退：只使用 detail 图
            if ctx._detail_images:
                ctx.image_result = ImageResult(
                    images=ctx._detail_images,
                    total_count=len(ctx._detail_images),
                    generated_at=datetime.now().isoformat()
                )

        return ctx
