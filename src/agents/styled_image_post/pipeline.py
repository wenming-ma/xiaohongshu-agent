"""StyledImagePostPipeline - 小红书图文帖子工具（支持参考图片）

封装完整的图文帖子创作和发布工作流：先识别推荐物品并收集参考图片，
再进行语义分组和内容创作，使配图中推荐内容的外观更精准。
"""

from datetime import datetime
from pathlib import Path

from ...core.base_pipeline import BasePipeline
from ...core.pipeline_registry import PipelineRegistry
from ...config.settings import PathConfig
from ...utils.logger import get_logger
from ...utils.file_ops import save_json
from .schemas import StyledImagePostInput, StyledImagePostOutput

logger = get_logger(__name__)


@PipelineRegistry.register
class StyledImagePostPipeline(BasePipeline[StyledImagePostInput, StyledImagePostOutput]):
    """小红书图文帖子工具（支持参考图片）

    封装完整的工作流：
    1. 研究主题（ResearchAgent）
    2. 识别推荐物品 + 用户确认 + 收集参考图片（CollectAgent）
    3. 语义分组（ImageAgent.compute_groups，感知参考图片）
    4. 创作内容（ContentAgent，按分组结构组织正文）
    5. 生成图片（ImageAgent，使用参考图片）
    6. 发布帖子（PublisherAgent）
    """

    name = "xiaohongshu_styled_image_post"
    description = """创建并发布小红书图文帖子（支持参考图片）。

该工具会执行完整的内容创作工作流：
- 在小红书平台研究目标主题，收集热门帖子和评论区信息
- 从研究数据中识别正面推荐的物品，让用户确认并收集参考图片
- 进行语义分组，将推荐物品和避雷内容智能分配到不同板块
- 根据研究结果生成符合小红书风格的标题、正文和话题标签
- 使用AI生成封面图和详情图（参考用户提供的产品图片）
- 自动发布到小红书平台

适用场景：产品推荐、穿搭分享、好物清单等需要精确展示推荐产品外观的图文内容。
目标平台：小红书（中国社交电商应用）
输出语言：中文
"""
    platform = "xiaohongshu"
    content_type = "styled_image_post"
    input_schema = StyledImagePostInput
    output_schema = StyledImagePostOutput

    async def execute(self, input_data: StyledImagePostInput) -> StyledImagePostOutput:
        """执行图文帖子工作流"""
        from .research import ResearchAgent
        from .content import ContentAgent
        from .image import ImageAgent
        from .publish import PublisherAgent
        from .collect import CollectAgent

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in input_data.topic if c.isalnum() or c in " -_")[:20]
        output_dir = PathConfig.IMAGE_PROJECT_DIR / f"{timestamp}-{safe_topic}-ref"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("StyledImagePostPipeline 开始执行")
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

            # Phase 2: 识别推荐物品 + 用户确认 + 收集参考图片
            logger.info("-" * 40)
            logger.info("Phase 2: 识别推荐物品与收集参考图片")
            logger.info("-" * 40)

            collect_agent = CollectAgent()
            ref_images = await collect_agent.forward(
                research=research,
                topic=input_data.topic,
                target_audience=input_data.audience,
                output_dir=output_dir,
            )
            save_json(output_dir / "reference_images.json", ref_images.model_dump())

            if ref_images.skipped:
                logger.info("参考图片收集: 已跳过")
            else:
                total_refs = sum(len(item.image_paths) for item in ref_images.items)
                logger.info(f"参考图片收集完成: {total_refs} 张图片")

            # Phase 3: 语义分组（感知参考图片）
            logger.info("-" * 40)
            logger.info("Phase 3: 语义分组")
            logger.info("-" * 40)

            image_agent = ImageAgent()
            groups = await image_agent.compute_groups(
                research=research,
                topic=input_data.topic,
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
                topic=input_data.topic,
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
                topic=input_data.topic,
                output_dir=output_dir,
                groups=groups,
                reference_images=ref_images,
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
            logger.info("StyledImagePostPipeline 执行完成")
            logger.info("=" * 60)

            return StyledImagePostOutput(
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
            logger.error(f"StyledImagePostPipeline 执行失败: {e}")
            import traceback
            traceback.print_exc()

            return StyledImagePostOutput(
                success=False,
                output_dir=str(output_dir),
                error_message=str(e),
            )
