from datetime import datetime
from pathlib import Path

from ...core.base_pipeline import BasePipeline
from ...core.pipeline_registry import PipelineRegistry
from ...config.settings import PathConfig
from ...utils.logger import get_logger
from ...utils.file_ops import save_json
from .schemas import XHSVideoPostInput, XHSVideoPostOutput

logger = get_logger(__name__)


@PipelineRegistry.register
class XHSVideoPostPipeline(BasePipeline[XHSVideoPostInput, XHSVideoPostOutput]):
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
        output_dir = PathConfig.VIDEO_PROJECT_DIR / f"{timestamp}-{safe_topic}"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("XHSVideoPostPipeline 开始执行")
        logger.info("=" * 60)
        logger.info(f"主题: {input_data.topic}")
        logger.info(f"受众: {input_data.audience}")
        logger.info(f"平台: {[p.value for p in input_data.platforms]}")
        logger.info(f"输出目录: {output_dir}")

        try:
            # Phase 1: 搜索视频
            logger.info("")
            logger.info("=" * 60)
            logger.info("Phase 1: 多平台视频搜索")
            logger.info("=" * 60)
            logger.info(f"搜索话题: {input_data.topic}")
            logger.info(f"目标平台: {', '.join([p.value for p in input_data.platforms])}")
            logger.info(f"最大视频数: {input_data.max_videos}")
            logger.info("")

            research_agent = ResearchAgent()
            research = await research_agent.forward(
                topic=input_data.topic,
                platforms=input_data.platforms,
                max_videos=input_data.max_videos,
                output_dir=output_dir,
            )
            save_json(output_dir / "research.json", research.model_dump())

            logger.info("")
            logger.info(f"✅ 搜索完成: 找到 {research.sources_count} 个高质量视频源")
            for i, source in enumerate(research.sources, 1):
                logger.info(f"   {i}. [{source.platform.value}] {source.title[:50]}...")
            logger.info("")

            # Phase 2: 下载最佳视频
            logger.info("=" * 60)
            logger.info("Phase 2: 视频下载与处理")
            logger.info("=" * 60)
            logger.info(f"准备下载 {len(research.sources)} 个视频（按互动量排序）")
            logger.info("")

            download_agent = DownloadAgent()
            download_result = await download_agent.forward(
                sources=research.sources,
                output_dir=output_dir,
            )
            save_json(output_dir / "download.json", download_result.model_dump())

            logger.info("")
            logger.info(f"✅ 下载完成: {download_result.local_path}")
            logger.info(f"   文件大小: {download_result.file_size_bytes / (1024*1024):.2f} MB")
            if download_result.transcription and download_result.transcription.success:
                logger.info(f"   转录文本: {len(download_result.transcription.transcript)} 字符")
            if download_result.subtitle and download_result.subtitle.success:
                logger.info(f"   字幕语言: {download_result.subtitle.language}")
                logger.info(f"   已翻译: {'是' if download_result.subtitle.translated else '否'}")
                logger.info(f"   字幕片段: {len(download_result.subtitle.segments)} 条")
            logger.info("")

            # Phase 3: 内容适配
            logger.info("=" * 60)
            logger.info("Phase 3: 小红书内容创作")
            logger.info("=" * 60)
            logger.info(f"基于视频内容创作中文文案...")
            logger.info("")

            content_agent = ContentAgent()
            content = await content_agent.forward(
                research=research,
                video_source=download_result.source,
                topic=input_data.topic,
                transcript=download_result.transcription,
            )
            save_json(output_dir / "content.json", content.model_dump())

            logger.info("")
            logger.info(f"✅ 内容创作完成")
            logger.info(f"   标题: {content.title}")
            logger.info(f"   正文预览: {content.body[:100]}...")
            logger.info(f"   话题标签: {', '.join(content.hashtags)}")
            logger.info("")

            # Phase 4: 发布
            if input_data.publish:
                logger.info("=" * 60)
                logger.info("Phase 4: 发布到小红书")
                logger.info("=" * 60)
                logger.info(f"准备发布视频...")
                logger.info("")

                publisher_agent = PublisherAgent()
                publish_result = await publisher_agent.forward(
                    content=content,
                    video_path=Path(download_result.local_path),
                    output_dir=output_dir,
                )
                save_json(output_dir / "publish.json", publish_result.model_dump())

                logger.info("")
                if publish_result.published:
                    logger.info(f"✅ 发布成功")
                    logger.info(f"   帖子链接: {publish_result.post_url}")
                else:
                    logger.warning(f"❌ 发布失败: {publish_result.error_message}")
                logger.info("")
            else:
                logger.info("=" * 60)
                logger.info("Phase 4: 跳过发布（--no-publish）")
                logger.info("=" * 60)
                logger.info("")
                publish_result = None

            logger.info("=" * 60)
            logger.info("✅ XHSVideoPostPipeline 执行完成")
            logger.info("=" * 60)
            logger.info(f"所有文件已保存到: {output_dir}")
            logger.info("")

            return XHSVideoPostOutput(
                success=True,
                title=content.title,
                body_preview=content.body[:200] if content.body else "",
                hashtags=content.hashtags,
                video_path=download_result.local_path,
                published=publish_result.published if publish_result else False,
                post_url=publish_result.post_url if publish_result else None,
                output_dir=str(output_dir),
            )

        except Exception as e:
            logger.error(f"XHSVideoPostPipeline 执行失败: {e}")
            import traceback
            traceback.print_exc()

            return XHSVideoPostOutput(
                success=False,
                output_dir=str(output_dir),
                error_message=str(e),
            )
