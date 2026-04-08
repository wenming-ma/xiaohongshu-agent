"""OutfitPostPipeline - 小红书穿搭搭配帖子

封装完整的穿搭搭配内容创作和发布工作流：
先与用户讨论确定搭配物品并收集参考图片，
再在小红书研究穿法灵感，分组、生成内容和图片，最后发布。
"""

from datetime import datetime
from pathlib import Path

from ...core.base_pipeline import BasePipeline
from ...core.pipeline_registry import PipelineRegistry
from ...config.settings import PathConfig
from ...utils.logger import get_logger
from ...utils.file_ops import save_json
from .schemas import OutfitPostInput, OutfitPostOutput

logger = get_logger(__name__)


@PipelineRegistry.register
class OutfitPostPipeline(BasePipeline[OutfitPostInput, OutfitPostOutput]):
    """小红书穿搭搭配帖子

    封装完整的工作流：
    1. 与用户讨论搭配物品 + 收集参考图片（DiscussAgent）
    2. 在小红书研究穿法灵感（ResearchAgent）
    3. 语义分组（ImageAgent.compute_groups）
    4. 创作内容（ContentAgent）
    5. 生成图片（ImageAgent，使用参考图片）
    6. 发布帖子（PublisherAgent）
    """

    name = "xiaohongshu_outfit_post"
    description = """创建并发布小红书穿搭搭配帖子。

该工具会执行完整的穿搭内容创作工作流：
- 通过飞书与用户讨论确定穿搭搭配物品
- 收集每个单品的参考图片
- 在小红书平台研究该搭配的各种穿法和搭配灵感
- 进行语义分组，将穿法灵感智能分配到不同板块
- 根据研究结果生成符合小红书风格的标题、正文和话题标签
- 使用AI生成配图（参考用户提供的单品图片）
- 自动发布到小红书平台

适用场景：穿搭分享、搭配推荐、穿法教程等需要展示具体单品外观的图文内容。
目标平台：小红书（中国社交电商应用）
输出语言：中文
"""
    platform = "xiaohongshu"
    content_type = "outfit_post"
    input_schema = OutfitPostInput
    output_schema = OutfitPostOutput

    async def execute(self, input_data: OutfitPostInput) -> OutfitPostOutput:
        """执行穿搭搭配帖子工作流"""
        from .discuss import DiscussAgent
        from .research import ResearchAgent
        from .content import ContentAgent
        from .image import ImageAgent
        from .publish import PublisherAgent

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in (input_data.topic or "outfit") if c.isalnum() or c in " -_")[:20]
        output_dir = PathConfig.OUTFIT_PROJECT_DIR / f"{timestamp}-{safe_topic}-outfit"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("OutfitPostPipeline 开始执行")
        logger.info("=" * 60)
        logger.info(f"风格提示: {input_data.topic or '(无)'}")
        logger.info(f"受众: {input_data.audience}")
        logger.info(f"输出目录: {output_dir}")

        try:
            # Phase 1: 与用户讨论搭配物品 + 收集参考图片
            logger.info("-" * 40)
            logger.info("Phase 1: 讨论搭配物品与收集参考图片")
            logger.info("-" * 40)

            discuss_agent = DiscussAgent()
            items, ref_images, research_topic = await discuss_agent.forward(
                output_dir=output_dir,
                topic_hint=input_data.topic,
            )

            if not items:
                return OutfitPostOutput(
                    success=False,
                    output_dir=str(output_dir),
                    error_message="用户未提供搭配物品",
                )

            save_json(output_dir / "discuss.json", {
                "items": [item.model_dump() for item in items],
                "reference_images": ref_images.model_dump(),
                "research_topic": research_topic,
            })
            logger.info(f"搭配物品: {', '.join(item.name for item in items)}")
            logger.info(f"研究主题: {research_topic}")

            # Phase 2: 在小红书研究穿法灵感
            logger.info("-" * 40)
            logger.info("Phase 2: 研究穿法灵感")
            logger.info("-" * 40)

            research_agent = ResearchAgent()
            research = await research_agent.forward(
                topic=research_topic,
                target_audience=input_data.audience,
                output_dir=output_dir,
            )
            save_json(output_dir / "research.json", research.model_dump())
            logger.info(f"研究完成: {len(research.items)} 个内容项")

            # Phase 3: 语义分组（感知参考图片）
            logger.info("-" * 40)
            logger.info("Phase 3: 语义分组")
            logger.info("-" * 40)

            image_agent = ImageAgent()
            groups = await image_agent.compute_groups(
                research=research,
                topic=research_topic,
                outfit_item_names=[item.name for item in items],
                ref_item_names=ref_images.get_item_names_with_images(),
            )
            save_json(output_dir / "groups.json", groups)
            logger.info(f"语义分组完成: {len(groups)} 个分组")

            # Phase 4: 内容创作
            logger.info("-" * 40)
            logger.info("Phase 4: 内容创作")
            logger.info("-" * 40)

            content_agent = ContentAgent()
            content = await content_agent.forward(
                research=research,
                topic=research_topic,
                groups=groups,
            )
            save_json(output_dir / "content.json", content.model_dump())
            logger.info(f"内容创作完成: {content.title}")

            # Phase 5: 图片生成（传入参考图片）
            logger.info("-" * 40)
            logger.info("Phase 5: 图片生成")
            logger.info("-" * 40)

            image_result = await image_agent.forward(
                content=content,
                research=research,
                topic=research_topic,
                output_dir=output_dir,
                groups=groups,
                reference_images=ref_images,
                outfit_item_names=[item.name for item in items],
            )
            save_json(output_dir / "image.json", image_result.model_dump())

            image_paths = [img.image_path for img in image_result.images]
            logger.info(f"图片生成完成: {len(image_paths)} 张")

            # Phase 6: 发布
            publish_result = None
            if input_data.publish:
                logger.info("-" * 40)
                logger.info("Phase 6: 发布到小红书")
                logger.info("-" * 40)

                publisher_agent = PublisherAgent()
                publish_result = await publisher_agent.forward(
                    content=content,
                    images=[Path(p) for p in image_paths],
                    output_dir=output_dir,
                )
                save_json(output_dir / "publish.json", publish_result.model_dump())
                logger.info(f"发布完成: {publish_result.published}")
            else:
                logger.info("-" * 40)
                logger.info("Phase 6: 跳过发布")
                logger.info("-" * 40)

            logger.info("=" * 60)
            logger.info("OutfitPostPipeline 执行完成")
            logger.info("=" * 60)

            return OutfitPostOutput(
                success=True,
                title=content.title,
                body_preview=content.body[:200] if content.body else "",
                hashtags=content.hashtags,
                image_count=len(image_paths),
                image_paths=image_paths,
                published=publish_result.published if publish_result else False,
                post_url=publish_result.post_url if publish_result and publish_result.post_url else None,
                output_dir=str(output_dir),
            )

        except Exception as e:
            logger.error(f"OutfitPostPipeline 执行失败: {e}")
            import traceback
            traceback.print_exc()

            return OutfitPostOutput(
                success=False,
                output_dir=str(output_dir),
                error_message=str(e),
            )
