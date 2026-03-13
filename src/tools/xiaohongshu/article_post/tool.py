"""XHS long-form article tool orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ....config.settings import PathConfig
from ....core.base_tool import BasePlatformTool
from ....core.tool_registry import ToolRegistry
from ....utils.file_ops import save_json
from ....utils.logger import get_logger
from .schemas import (
    XHSArticlePostInput,
    XHSArticlePostOutput,
)

logger = get_logger(__name__)


@ToolRegistry.register
class XHSArticlePostTool(BasePlatformTool[XHSArticlePostInput, XHSArticlePostOutput]):
    name = "xiaohongshu_article_post"
    description = """创建并发布小红书长文。

该工具会执行完整的长文工作流：
- 深度搜索海外高质量女性向数字媒体内容
- 提取高价值文章与视频信息，必要时转录视频
- 生成适配小红书的中文长文与 AI 配图
- 自动发布到小红书长文编辑器
"""
    platform = "xiaohongshu"
    content_type = "article_post"
    input_schema = XHSArticlePostInput
    output_schema = XHSArticlePostOutput

    async def execute(self, input_data: XHSArticlePostInput) -> XHSArticlePostOutput:
        from .content import ContentAgent
        from .image import ImageAgent
        from .publish import PublisherAgent
        from .research import ResearchAgent

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in input_data.topic if c.isalnum() or c in " -_")[:32]
        output_dir = PathConfig.ARTICLE_PROJECT_DIR / f"{timestamp}-{safe_topic}"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("XHSArticlePostTool 开始执行")
        logger.info("=" * 60)
        logger.info("主题: %s", input_data.topic)
        logger.info("受众: %s", input_data.audience)
        logger.info("策略: %s", input_data.strategy.value)
        logger.info("生成图片: %s", input_data.generate_images)
        logger.info("发布: %s", input_data.publish)
        logger.info("输出目录: %s", output_dir)

        try:
            logger.info("-" * 40)
            logger.info("Phase 1: 深度研究")
            logger.info("-" * 40)
            research_agent = ResearchAgent()
            research = await research_agent.forward(
                topic=input_data.topic,
                target_audience=input_data.audience,
                strategy=input_data.strategy,
                output_dir=output_dir,
            )
            save_json(output_dir / "research.json", research.model_dump())

            logger.info("-" * 40)
            logger.info("Phase 2: 长文创作")
            logger.info("-" * 40)
            content_agent = ContentAgent()
            content = await content_agent.forward(
                research=research,
                topic=input_data.topic,
                target_audience=input_data.audience,
                requested_strategy=input_data.strategy,
                generate_images=input_data.generate_images,
            )
            save_json(output_dir / "content.json", content.model_dump())

            image_result = None
            image_paths: list[str] = []
            if input_data.generate_images:
                logger.info("-" * 40)
                logger.info("Phase 3: 配图生成")
                logger.info("-" * 40)
                image_agent = ImageAgent()
                image_result = await image_agent.forward(
                    content=content,
                    research=research,
                    topic=input_data.topic,
                    output_dir=output_dir,
                )
                save_json(output_dir / "image.json", image_result.model_dump())
                image_paths = [item.image_path for item in image_result.images]
            else:
                logger.info("-" * 40)
                logger.info("Phase 3: 跳过配图生成")
                logger.info("-" * 40)

            publish_result = None
            if input_data.publish:
                logger.info("-" * 40)
                logger.info("Phase 4: 发布长文")
                logger.info("-" * 40)
                publisher_agent = PublisherAgent()
                publish_result = await publisher_agent.forward(
                    content=content,
                    images=[Path(path) for path in image_paths],
                    output_dir=output_dir,
                )
                save_json(output_dir / "publish.json", publish_result.model_dump())
            else:
                logger.info("-" * 40)
                logger.info("Phase 4: 跳过发布")
                logger.info("-" * 40)

            logger.info("=" * 60)
            logger.info("XHSArticlePostTool 执行完成")
            logger.info("=" * 60)

            return XHSArticlePostOutput(
                success=True,
                title=content.title,
                body_preview=content.rendered_body[:240] if content.rendered_body else "",
                hashtags=content.hashtags,
                image_count=len(image_paths),
                image_paths=image_paths,
                published=publish_result.published if publish_result else False,
                post_url=publish_result.post_url if publish_result and publish_result.post_url else None,
                output_dir=str(output_dir),
            )
        except Exception as exc:
            logger.error("XHSArticlePostTool 执行失败: %s", exc)
            import traceback

            traceback.print_exc()
            return XHSArticlePostOutput(
                success=False,
                output_dir=str(output_dir),
                error_message=str(exc),
            )
