"""
测试视频帖子完整流程: Research → Download(+Transcribe) → Content → Publish

使用方法:
    # 默认参数运行（不发布）
    uv run python tests/test_video_post.py

    # 指定主题
    uv run python tests/test_video_post.py --topic "AI编程工具"

    # 指定平台（x / instagram / tiktok / facebook）
    uv run python tests/test_video_post.py --topic "咖啡拉花" --platforms x tiktok

    # 实际发布到小红书
    uv run python tests/test_video_post.py --topic "东京探店" --publish
"""
import argparse
import asyncio
import logging
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

# Suppress logfire warning
os.environ["LOGFIRE_IGNORE_NO_CONFIG"] = "1"

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

from src.agents.video_post import XHSVideoPostPipeline, XHSVideoPostInput
from src.agents.video_post.schemas import Platform


def parse_args():
    parser = argparse.ArgumentParser(description="测试 XHSVideoPostPipeline 完整流程")
    parser.add_argument("--topic", default="cute cats compilation", help="搜索主题")
    parser.add_argument("--audience", default="年轻女性，喜欢可爱事物", help="目标受众")
    parser.add_argument("--platforms", nargs="+", default=["x", "instagram", "facebook", "tiktok"],
                        choices=["x", "instagram", "facebook", "tiktok"], help="搜索平台")
    parser.add_argument("--max-videos", type=int, default=3, help="最大搜索视频数")
    parser.add_argument("--publish", action="store_true", help="是否实际发布到小红书（默认不发布）")
    return parser.parse_args()


async def main():
    args = parse_args()

    platform_map = {
        "x": Platform.X,
        "instagram": Platform.INSTAGRAM,
        "facebook": Platform.FACEBOOK,
        "tiktok": Platform.TIKTOK,
    }
    platforms = [platform_map[p] for p in args.platforms]

    input_data = XHSVideoPostInput(
        topic=args.topic,
        audience=args.audience,
        platforms=platforms,
        max_videos=args.max_videos,
        publish=args.publish,
    )

    print("=" * 60)
    print("XHSVideoPostPipeline 完整流程测试")
    print("=" * 60)
    print(f"主题: {input_data.topic}")
    print(f"受众: {input_data.audience}")
    print(f"平台: {[p.value for p in input_data.platforms]}")
    print(f"最大视频数: {input_data.max_videos}")
    print(f"发布: {input_data.publish}")
    print("=" * 60)
    print()

    tool = XHSVideoPostPipeline()
    result = await tool.execute(input_data)

    print()
    print("=" * 60)
    print("执行结果")
    print("=" * 60)
    print(f"成功: {result.success}")
    if result.success:
        print(f"标题: {result.title}")
        print(f"正文预览: {result.body_preview}")
        print(f"标签: {result.hashtags}")
        print(f"视频路径: {result.video_path}")
        print(f"已发布: {result.published}")
        print(f"帖子链接: {result.post_url or '(未发布)'}")
        print(f"输出目录: {result.output_dir}")
    else:
        print(f"错误: {result.error_message}")
        print(f"输出目录: {result.output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
