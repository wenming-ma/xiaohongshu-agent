"""
测试 OutfitPostPipeline 完整流程

使用方法:
    # Mock 模式（默认）— 跳过飞书交互，用预设搭配单品
    uv run python tests/test_outfit_post.py

    # 自定义单品
    uv run python tests/test_outfit_post.py --items "牛仔外套,白T恤,黑色直筒裤,帆布鞋"

    # 自定义风格提示
    uv run python tests/test_outfit_post.py --topic "通勤穿搭"

    # 真实飞书交互模式（需要飞书配置）
    uv run python tests/test_outfit_post.py --live

    # 带发布
    uv run python tests/test_outfit_post.py --publish
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()
os.environ["LOGFIRE_IGNORE_NO_CONFIG"] = "1"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


# Fix Windows console encoding for Chinese output
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

from src.agents.outfit_post import OutfitPostInput, OutfitPostPipeline
from src.agents.outfit_post.schemas import (
    OutfitItem,
    OutfitPostOutput,
    ReferenceImageResult,
)
from src.config.settings import PathConfig, ResearchConfig, ReviewConfig, ImageConfig
from src.utils.file_ops import save_json
from src.utils.logger import get_logger

# ── 降低研究深度要求，加速测试 ──
ResearchConfig.MIN_POSTS_RESEARCHED = 2        # 默认 21 → 只需研究 2 个帖子
ResearchConfig.VALIDATION_MAX_RETRIES = 2      # 默认 15 → 验证不过最多重试 2 轮
ReviewConfig.MAX_ITERATIONS = 2                # 默认 10 → 内容审核最多 2 轮
ImageConfig.GROUPING_REVIEW_MAX_RETRIES = 2    # 默认 20 → 分组审核最多 2 轮

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试 OutfitPostPipeline 完整流程")
    parser.add_argument("--topic", default="休闲穿搭", help="风格提示")
    parser.add_argument("--audience", default="年轻女性", help="目标受众")
    parser.add_argument(
        "--items",
        default="白色衬衫,高腰阔腿裤,小白鞋",
        help="Mock 模式下的搭配单品（逗号分隔）",
    )
    parser.add_argument("--publish", action="store_true", help="是否实际发布到小红书")
    parser.add_argument("--live", action="store_true", help="真实飞书交互模式（不 mock）")
    return parser.parse_args()


async def run_mock(args: argparse.Namespace) -> OutfitPostOutput:
    """Mock 模式：跳过 DiscussAgent，直接用预设单品运行后续阶段"""
    from src.agents.outfit_post.research import ResearchAgent
    from src.agents.outfit_post.content import ContentAgent
    from src.agents.outfit_post.image import ImageAgent
    from src.agents.outfit_post.publish import PublisherAgent

    # 构建预设数据
    item_names = [name.strip() for name in args.items.split(",") if name.strip()]
    items = [OutfitItem(name=name) for name in item_names]
    ref_images = ReferenceImageResult(skipped=True)

    search_names = item_names[:4]
    items_str = "、".join(search_names)
    research_topic = f"{args.topic}：{items_str} 穿法搭配" if args.topic else f"{items_str} 穿搭穿法"

    # 输出目录
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_topic = "".join(c for c in (args.topic or "outfit") if c.isalnum() or c in " -_")[:20]
    output_dir = PathConfig.OUTFIT_PROJECT_DIR / f"{timestamp}-{safe_topic}-outfit"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("[MOCK] 搭配单品: %s", ", ".join(item_names))
    logger.info("[MOCK] 研究主题: %s", research_topic)
    logger.info("输出目录: %s", output_dir)
    logger.info("=" * 60)

    save_json(output_dir / "discuss.json", {
        "items": [item.model_dump() for item in items],
        "reference_images": ref_images.model_dump(),
        "research_topic": research_topic,
    })

    try:
        # Phase 2: 研究穿法灵感
        logger.info("-" * 40)
        logger.info("Phase 2: 研究穿法灵感")
        logger.info("-" * 40)

        research_agent = ResearchAgent()
        research = await research_agent.forward(
            topic=research_topic,
            target_audience=args.audience,
            output_dir=output_dir,
        )
        save_json(output_dir / "research.json", research.model_dump())
        logger.info("研究完成: %d 个内容项", len(research.items))

        # Phase 3: 语义分组
        logger.info("-" * 40)
        logger.info("Phase 3: 语义分组")
        logger.info("-" * 40)

        image_agent = ImageAgent()
        groups = await image_agent.compute_groups(
            research=research,
            topic=research_topic,
            ref_item_names=ref_images.get_item_names_with_images(),
        )
        save_json(output_dir / "groups.json", groups)
        logger.info("语义分组完成: %d 个分组", len(groups))

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
        logger.info("内容创作完成: %s", content.title)

        # Phase 5: 图片生成
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
        )
        save_json(output_dir / "image.json", image_result.model_dump())

        image_paths = [img.image_path for img in image_result.images]
        logger.info("图片生成完成: %d 张", len(image_paths))

        # Phase 6: 发布
        publish_result = None
        if args.publish:
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
        else:
            logger.info("Phase 6: 跳过发布")

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
        logger.error("Pipeline 执行失败: %s", e)
        import traceback
        traceback.print_exc()
        return OutfitPostOutput(
            success=False,
            output_dir=str(output_dir),
            error_message=str(e),
        )


async def run_live(args: argparse.Namespace) -> OutfitPostOutput:
    """Live 模式：运行完整 pipeline（含飞书交互）"""
    pipeline = OutfitPostPipeline()
    return await pipeline.execute(
        OutfitPostInput(
            topic=args.topic,
            audience=args.audience,
            publish=args.publish,
        )
    )


async def main() -> None:
    args = parse_args()

    if args.live:
        print("=" * 60)
        print("LIVE 模式：将通过飞书与用户交互")
        print("=" * 60)
        result = await run_live(args)
    else:
        print("=" * 60)
        print(f"MOCK 模式：预设搭配单品 = {args.items}")
        print("=" * 60)
        result = await run_mock(args)

    # 输出结果
    print()
    print("=" * 60)
    print("OutfitPostPipeline 执行结果")
    print("=" * 60)
    print(f"成功: {result.success}")
    print(f"标题: {result.title}")
    if result.body_preview:
        print(f"正文预览: {result.body_preview[:200]}")
    print(f"Hashtags: {result.hashtags}")
    print(f"图片数: {result.image_count}")
    if result.image_paths:
        for i, path in enumerate(result.image_paths):
            print(f"  图片 {i+1}: {path}")
    print(f"已发布: {result.published}")
    print(f"帖子链接: {result.post_url or '(未发布)'}")
    print(f"输出目录: {result.output_dir}")
    if result.error_message:
        print(f"错误: {result.error_message}")


if __name__ == "__main__":
    asyncio.run(main())
