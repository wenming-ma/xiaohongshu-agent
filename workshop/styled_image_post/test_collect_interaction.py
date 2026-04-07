"""
直接测试 CollectAgent 的 Feishu 交互（注入模拟研究数据）

用法:
    uv run python workshop/styled_image_post/test_collect_interaction.py
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger, setup_logging  # noqa: E402
from src.agents.styled_image_post.schemas import (  # noqa: E402
    ResearchResult,
    ResearchItem,
    ReferenceImageResult,
)
from src.agents.styled_image_post.collect import CollectAgent  # noqa: E402

setup_logging()
logger = get_logger(__name__)


# 模拟研究数据（包含推荐物品）
MOCK_RESEARCH = ResearchResult(
    summary="小个子秋冬穿搭指南，帮助155-160cm女生显高10cm的穿搭公式",
    items=[
        ResearchItem(
            title="白色贝雷帽",
            content="推荐小个子秋冬必备单品：白色贝雷帽，小巧精致的帽型不会压头显矮，秋冬搭配大衣或毛衣都很好看，可以营造法式高级感",
            item_type="推荐单品",
        ),
        ResearchItem(
            title="高腰阔腿裤",
            content="强烈推荐高腰阔腿裤，小个子秋冬显高神器，高腰设计拉长腿部比例，阔腿版型遮肉显瘦，配上米白色或驼色显腿长10cm",
            item_type="推荐单品",
        ),
        ResearchItem(
            title="厚底马丁靴",
            content="厚底马丁靴是小个子秋冬增高好物，鞋底厚度3-5cm瞬间显高，百搭牛仔裤或半身裙都很好看，黑色款最经典实用",
            item_type="推荐单品",
        ),
        ResearchItem(
            title="短款羊羔绒外套",
            content="推荐小个子穿短款外套，腰线以上的长度不会截断腿部比例，羊羔绒材质保暖又时髦，配高腰裤或半身裙显腿长",
            item_type="推荐单品",
        ),
        ResearchItem(
            title="避雷长款大衣",
            content="避雷：过膝长款大衣对于小个子不友好，会把人拦腰截断显矮，如果一定要穿建议选择单色款并搭配高跟鞋",
            item_type="避雷提醒",
        ),
    ],
    keywords=["小个子", "秋冬穿搭", "显高", "搭配"],
)


async def main() -> None:
    topic = "小个子秋冬穿搭指南｜显高10cm的搭配公式"
    audience = "155-160cm的小个子女生"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = PROJECT_ROOT / "posts" / "image-posts" / f"{timestamp}-collect-test"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("CollectAgent 交互测试")
    logger.info(f"主题: {topic}")
    logger.info(f"受众: {audience}")
    logger.info(f"输出目录: {output_dir}")
    logger.info("=" * 60)

    agent = CollectAgent()
    result: ReferenceImageResult = await agent.forward(
        research=MOCK_RESEARCH,
        topic=topic,
        target_audience=audience,
        output_dir=output_dir,
    )

    logger.info("=" * 60)
    if result.skipped:
        logger.info("结果: 已跳过")
    else:
        logger.info(f"结果: {len(result.items)} 个物品")
        for item in result.items:
            logger.info(f"  - {item.item_name}: {len(item.image_paths)} 张图片")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
