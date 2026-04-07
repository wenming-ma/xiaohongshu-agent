"""
最低配置快速测试脚本 - 运行一轮完整的 StyledImagePost 测试（不发布）

用法:
    uv run python workshop/styled_image_post/test_run_min.py
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")

# 降低各阶段的配置要求，以便快速测试
from src.config import settings  # noqa: E402
settings.ResearchConfig.MIN_POSTS_RESEARCHED = 3
settings.ResearchConfig.MIN_KEY_INFOS = 5
settings.ResearchConfig.MIN_CASES = 3
settings.ResearchConfig.VALIDATION_MAX_RETRIES = 2
settings.ResearchConfig.VALIDATION_PASS_SCORE = 0
settings.ReviewConfig.MAX_ITERATIONS = 1
settings.ReviewConfig.PASS_SCORE = 0
settings.ImageConfig.GROUPING_REVIEW_MAX_RETRIES = 1
settings.ImageConfig.MAX_DETAIL_IMAGES = 2
settings.ImageConfig.MIN_DETAIL_IMAGES = 1

import logfire  # noqa: E402

logfire.configure(
    send_to_logfire="if-token-present",
    environment="development",
    service_name="xiaohongshu-agent-test",
)
logfire.instrument_pydantic_ai()

from src.agents.styled_image_post import StyledImagePostPipeline  # noqa: E402
from src.agents.styled_image_post.schemas import StyledImagePostInput  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)


async def main() -> None:
    topic = "小个子秋冬穿搭指南｜显高10cm的搭配公式"
    audience = "155-160cm的小个子女生"

    logger.info("=" * 60)
    logger.info("StyledImagePost 最低配置测试")
    logger.info(f"主题: {topic}")
    logger.info(f"受众: {audience}")
    logger.info("publish=False（不发布）")
    logger.info("=" * 60)

    pipeline = StyledImagePostPipeline()
    result = await pipeline.execute(StyledImagePostInput(
        topic=topic,
        audience=audience,
        publish=False,
    ))

    logger.info("=" * 60)
    if result.success:
        logger.info("✅ 测试成功!")
        logger.info(f"标题: {result.title}")
        logger.info(f"图片数: {result.image_count}")
        logger.info(f"输出目录: {result.output_dir}")
    else:
        logger.error(f"❌ 测试失败: {result.error_message}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
