"""XHSImagePostTool - 小红书图文帖子工具

封装完整的图文帖子创作和发布工作流。
"""

from datetime import datetime
from pathlib import Path

from ....core.base_tool import BasePlatformTool
from ....core.tool_registry import ToolRegistry
from ....utils.logger import get_logger
from ....utils.file_ops import save_json
from .schemas import XHSImagePostInput, XHSImagePostOutput

logger = get_logger(__name__)


@ToolRegistry.register
class XHSImagePostTool(BasePlatformTool[XHSImagePostInput, XHSImagePostOutput]):
    """小红书图文帖子工具

    封装完整的工作流：
    1. 研究主题（ResearchAgent）
    2. 创作内容（ContentAgent）
    3. 生成图片（ImageAgent）
    4. 发布帖子（PublisherAgent）
    """

    name = "xiaohongshu_image_post"
    description = """创建并发布小红书图文帖子。

该工具会执行完整的内容创作工作流：
- 在小红书平台研究目标主题，收集热门帖子和评论区信息
- 根据研究结果生成符合小红书风格的标题、正文和话题标签
- 使用AI生成封面图和详情图
- 自动发布到小红书平台

适用场景：产品推荐、生活技巧、旅行攻略、避坑指南等图文内容。
目标平台：小红书（中国社交电商应用）
输出语言：中文
"""
    platform = "xiaohongshu"
    content_type = "image_post"
    input_schema = XHSImagePostInput
    output_schema = XHSImagePostOutput

    async def execute(self, input_data: XHSImagePostInput) -> XHSImagePostOutput:
        """执行图文帖子工作流"""
        from .research import ResearchAgent
        from .content import ContentAgent
        from .image import ImageAgent
        from .publish import PublisherAgent

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in input_data.topic if c.isalnum() or c in " -_")[:20]
        output_dir = Path("posts") / f"{timestamp}-{safe_topic}"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("XHSImagePostTool 开始执行")
        logger.info("=" * 60)
        logger.info(f"主题: {input_data.topic}")
        logger.info(f"受众: {input_data.audience}")
        logger.info(f"输出目录: {output_dir}")

        try:
            # Phase 1: 研究
            logger.info("-" * 40)
            logger.info("Phase 1: 研究主题")
            logger.info("-" * 40)

            research_agent = ResearchAgent()
            research = await research_agent.forward(
                topic=input_data.topic,
                target_audience=input_data.audience,
                output_dir=output_dir,
            )
            save_json(output_dir / "research.json", research.model_dump())

            logger.info(f"研究完成: {len(research.items)} 个内容项")

            # Phase 2: 内容创作
            logger.info("-" * 40)
            logger.info("Phase 2: 内容创作")
            logger.info("-" * 40)

            content_agent = ContentAgent()
            content = await content_agent.forward(
                research=research,
                topic=input_data.topic,
            )
            save_json(output_dir / "content.json", content.model_dump())

            logger.info(f"内容创作完成: {content.title}")

            # Phase 3: 图片生成
            logger.info("-" * 40)
            logger.info("Phase 3: 图片生成")
            logger.info("-" * 40)

            image_agent = ImageAgent()
            image_result = await image_agent.forward(
                content=content,
                research=research,
                topic=input_data.topic,
                output_dir=output_dir,
            )
            save_json(output_dir / "image.json", image_result.model_dump())

            image_paths = [img.image_path for img in image_result.images]
            logger.info(f"图片生成完成: {len(image_paths)} 张")

            # Phase 4: 发布
            logger.info("-" * 40)
            logger.info("Phase 4: 发布到小红书")
            logger.info("-" * 40)

            publisher_agent = PublisherAgent()
            publish_result = await publisher_agent.forward(
                content=content,
                images=[Path(p) for p in image_paths],
                output_dir=output_dir,
            )
            save_json(output_dir / "publish.json", publish_result.model_dump())

            logger.info(f"发布完成: {publish_result.published}")

            logger.info("=" * 60)
            logger.info("XHSImagePostTool 执行完成")
            logger.info("=" * 60)

            return XHSImagePostOutput(
                success=True,
                title=content.title,
                body_preview=content.body[:200] if content.body else "",
                hashtags=content.hashtags,
                image_count=len(image_paths),
                image_paths=image_paths,
                published=publish_result.published,
                post_url=publish_result.post_url,
                output_dir=str(output_dir),
            )

        except Exception as e:
            logger.error(f"XHSImagePostTool 执行失败: {e}")
            import traceback
            traceback.print_exc()

            return XHSImagePostOutput(
                success=False,
                output_dir=str(output_dir),
                error_message=str(e),
            )
