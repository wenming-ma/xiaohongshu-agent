from datetime import datetime
from pathlib import Path

from ....core.base_tool import BasePlatformTool
from ....core.tool_registry import ToolRegistry
from ....utils.logger import get_logger
from ....utils.file_ops import save_json
from .schemas import XHSVideoPostInput, XHSVideoPostOutput

logger = get_logger(__name__)


@ToolRegistry.register
class XHSVideoPostTool(BasePlatformTool[XHSVideoPostInput, XHSVideoPostOutput]):
    name = "xiaohongshu_video_post"
    description = "搜索多平台热门视频并发布到小红书。支持从 X、Instagram、Facebook、TikTok 搜索视频，使用 yt-dlp 下载，生成小红书适配内容后自动发布。"
    platform = "xiaohongshu"
    content_type = "video_post"
    input_schema = XHSVideoPostInput
    output_schema = XHSVideoPostOutput

    async def execute(self, input_data: XHSVideoPostInput) -> XHSVideoPostOutput:
        from .research import ResearchAgent
        from .download import DownloadAgent
        from .content import ContentAgent
        from .publish import PublisherAgent

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in input_data.topic if c.isalnum() or c in " -_")[:20]
        output_dir = Path("posts") / f"{timestamp}-video-{safe_topic}"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("XHSVideoPostTool 开始执行")
        logger.info("=" * 60)
        logger.info(f"主题: {input_data.topic}")
        logger.info(f"受众: {input_data.audience}")
        logger.info(f"平台: {[p.value for p in input_data.platforms]}")
        logger.info(f"输出目录: {output_dir}")

        try:
            # Phase 1: 搜索视频
            logger.info("-" * 40)
            logger.info("Phase 1: 多平台视频搜索")
            logger.info("-" * 40)

            research_agent = ResearchAgent()
            research = await research_agent.forward(
                topic=input_data.topic,
                platforms=input_data.platforms,
                max_videos=input_data.max_videos,
                output_dir=output_dir,
            )
            save_json(output_dir / "research.json", research.model_dump())
            logger.info(f"搜索完成: {research.sources_count} 个视频源")

            # Phase 2: 下载最佳视频
            logger.info("-" * 40)
            logger.info("Phase 2: 视频下载")
            logger.info("-" * 40)

            download_agent = DownloadAgent()
            download_result = await download_agent.forward(
                sources=research.sources,
                output_dir=output_dir,
            )
            save_json(output_dir / "download.json", download_result.model_dump())
            logger.info(f"下载完成: {download_result.local_path}")

            # Phase 3: 内容适配
            logger.info("-" * 40)
            logger.info("Phase 3: 内容适配")
            logger.info("-" * 40)

            content_agent = ContentAgent()
            content = await content_agent.forward(
                research=research,
                video_source=download_result.source,
                topic=input_data.topic,
            )
            save_json(output_dir / "content.json", content.model_dump())
            logger.info(f"内容创作完成: {content.title}")

            # Phase 4: 发布
            logger.info("-" * 40)
            logger.info("Phase 4: 发布到小红书")
            logger.info("-" * 40)

            publisher_agent = PublisherAgent()
            publish_result = await publisher_agent.forward(
                content=content,
                video_path=Path(download_result.local_path),
                output_dir=output_dir,
            )
            save_json(output_dir / "publish.json", publish_result.model_dump())
            logger.info(f"发布完成: {publish_result.published}")

            logger.info("=" * 60)
            logger.info("XHSVideoPostTool 执行完成")
            logger.info("=" * 60)

            return XHSVideoPostOutput(
                success=True,
                title=content.title,
                body_preview=content.body[:200] if content.body else "",
                hashtags=content.hashtags,
                video_path=download_result.local_path,
                published=publish_result.published,
                post_url=publish_result.post_url,
                output_dir=str(output_dir),
            )

        except Exception as e:
            logger.error(f"XHSVideoPostTool 执行失败: {e}")
            import traceback
            traceback.print_exc()

            return XHSVideoPostOutput(
                success=False,
                output_dir=str(output_dir),
                error_message=str(e),
            )
