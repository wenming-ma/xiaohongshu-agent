"""
测试 XHSArticlePostPipeline 完整流程

使用方法:
    uv run python tests/test_article_post.py --topic "spring capsule wardrobe"
    uv run python tests/test_article_post.py --strategy repurpose_article
    uv run python tests/test_article_post.py --strategy repurpose_video --publish
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()
os.environ["LOGFIRE_IGNORE_NO_CONFIG"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

from src.agents.article_post import XHSArticlePostInput, XHSArticlePostPipeline
from src.agents.article_post.schemas import ArticleStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试 XHSArticlePostPipeline 完整流程")
    parser.add_argument("--topic", default="spring capsule wardrobe", help="研究主题")
    parser.add_argument("--audience", default="25-35岁中文女性用户", help="目标受众")
    parser.add_argument(
        "--strategy",
        choices=[strategy.value for strategy in ArticleStrategy],
        default=ArticleStrategy.AUTO.value,
        help="内容策略",
    )
    parser.add_argument("--publish", action="store_true", help="是否实际发布到小红书")
    parser.add_argument("--no-image", action="store_true", help="跳过图片生成")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    tool = XHSArticlePostPipeline()
    result = await tool.execute(
        XHSArticlePostInput(
            topic=args.topic,
            audience=args.audience,
            publish=args.publish,
            generate_images=not args.no_image,
            strategy=ArticleStrategy(args.strategy),
        )
    )

    print("=" * 60)
    print("XHSArticlePostPipeline 执行结果")
    print("=" * 60)
    print(f"成功: {result.success}")
    print(f"标题: {result.title}")
    print(f"正文预览: {result.body_preview[:200]}")
    print(f"Hashtags: {result.hashtags}")
    print(f"图片数: {result.image_count}")
    print(f"已发布: {result.published}")
    print(f"帖子链接: {result.post_url or '(未发布)'}")
    print(f"输出目录: {result.output_dir}")
    if result.error_message:
        print(f"错误: {result.error_message}")


if __name__ == "__main__":
    asyncio.run(main())
