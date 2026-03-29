"""
迭代执行 workshop/article_post/topics.json 中的话题，仅调用 XHSArticlePostPipeline。

用法:
    uv run python workshop/article_post/run.py
    uv run python workshop/article_post/run.py --start-index 3
    uv run python workshop/article_post/run.py --limit 2 --strategy repurpose_article
    uv run python workshop/article_post/run.py --no-publish
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import logfire  # noqa: E402

logfire.configure(
    send_to_logfire="if-token-present",
    environment="development",
    service_name="xiaohongshu-agent-article-batch",
)
logfire.instrument_pydantic_ai()

from src.agents.article_post import XHSArticlePostInput, XHSArticlePostPipeline  # noqa: E402
from src.agents.article_post.schemas import ArticleStrategy  # noqa: E402
from src.utils.feishu_notifier import get_feishu_notifier  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402


setup_logging()
logger = get_logger(__name__)


def load_topics(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("topics.json 顶层必须是数组")
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or not item.get("topic") or not item.get("audience"):
            raise ValueError(f"第 {i} 项缺少 topic 或 audience")
    return raw


def resolve_strategy(item: dict[str, Any], override: str | None) -> ArticleStrategy:
    if override:
        return ArticleStrategy(override)
    raw = str(item.get("strategy") or "").strip()
    if raw in {strategy.value for strategy in ArticleStrategy}:
        return ArticleStrategy(raw)
    return ArticleStrategy.AUTO


async def run_single(
    item: dict[str, Any],
    idx: int,
    total: int,
    *,
    max_retries: int,
    retry_delay: int,
    publish: bool,
    generate_images: bool,
    strategy_override: str | None,
    notify_feishu: bool = True,
) -> dict[str, Any]:
    topic = item["topic"].strip()
    audience = item["audience"].strip()
    strategy = resolve_strategy(item, strategy_override)

    logger.info("[%d/%d] 话题: %s", idx, total, topic)
    logger.info("  受众: %s", audience)
    logger.info("  策略: %s", strategy.value)
    logger.info("  发布: %s", publish)
    logger.info("  生成图片: %s", generate_images)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.warning("  重试 %d/%d，等待 %ds …", attempt, max_retries, retry_delay)
            await asyncio.sleep(retry_delay)

        try:
            tool = XHSArticlePostPipeline()
            result = await tool.execute(
                XHSArticlePostInput(
                    topic=topic,
                    audience=audience,
                    publish=publish,
                    generate_images=generate_images,
                    strategy=strategy,
                )
            )
            payload = result.model_dump()
            payload["topic"] = topic
            payload["audience"] = audience
            payload["strategy"] = strategy.value

            if result.success:
                logger.info("  成功: %s", result.title or topic)
                logger.info("  输出目录: %s", result.output_dir)

                if result.published and notify_feishu:
                    try:
                        notifier = get_feishu_notifier()
                        lines = [
                            "✅ 长文发布成功",
                            f"主题：{topic}",
                            f"标题：{result.title or '无'}",
                            f"策略：{strategy.value}",
                            f"话题：{' '.join(result.hashtags) if result.hashtags else '无'}",
                            f"帖子链接：{result.post_url or '未获取到'}",
                        ]
                        await notifier.send_message("\n".join(lines))
                    except Exception:
                        logger.warning("飞书通知发送失败", exc_info=True)

                return payload

            last_error = result.error_message or "未知错误"
            logger.error("  失败: %s", last_error)
        except Exception:
            import traceback

            last_error = traceback.format_exc()
            logger.exception("  执行异常")

    return {
        "success": False,
        "topic": topic,
        "audience": audience,
        "strategy": strategy.value,
        "error_message": last_error,
    }


async def run_batch(args: argparse.Namespace) -> int:
    topics = load_topics(args.topics_file)

    start = args.start_index - 1
    selected = topics[start:]
    if args.limit is not None:
        selected = selected[: args.limit]

    if not selected:
        logger.warning("没有可处理的话题")
        return 0

    total = len(selected)
    base_idx = args.start_index

    logger.info("=" * 60)
    logger.info("XHS Article Post 批量执行")
    logger.info("话题文件: %s", args.topics_file)
    logger.info("范围: #%d ~ #%d (共 %d 个)", base_idx, base_idx + total - 1, total)
    logger.info(
        "最大重试: %d  重试间隔: %ds  发布: %s  策略覆盖: %s",
        args.max_retries,
        args.retry_delay,
        not args.no_publish,
        args.strategy or "无",
    )
    logger.info("生成图片: %s", not args.no_image)
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, item in enumerate(selected):
        idx = base_idx + i
        result = await run_single(
            item,
            idx,
            base_idx + total - 1,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            publish=not args.no_publish,
            generate_images=not args.no_image,
            strategy_override=args.strategy,
            notify_feishu=not args.no_feishu,
        )
        results.append(result)

        if not result.get("success"):
            failed.append(result)

        if i < total - 1 and args.sleep is not None and args.sleep > 0:
            logger.info("休眠 %d 秒 (%.0f 分钟) 后继续 …", args.sleep, args.sleep / 60)
            await asyncio.sleep(args.sleep)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = SCRIPT_DIR / f"article_post_summary_{ts}.json"
    summary = {
        "timestamp": ts,
        "publish": not args.no_publish,
        "generate_images": not args.no_image,
        "strategy_override": args.strategy,
        "total": total,
        "success": total - len(failed),
        "failed": len(failed),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("汇总文件: %s", summary_path)

    if failed:
        failed_path = SCRIPT_DIR / f"article_post_failed_{ts}.json"
        failed_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("失败列表: %s", failed_path)

    logger.info("=" * 60)
    logger.info("完成  成功: %d / %d  失败: %d / %d", total - len(failed), total, len(failed), total)
    logger.info("=" * 60)

    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量执行 XHS Article Post")
    parser.add_argument("--topics-file", type=Path, default=SCRIPT_DIR / "topics.json", help="话题 JSON 文件")
    parser.add_argument("--start-index", type=int, default=1, help="从第几个话题开始 (1-based)")
    parser.add_argument("--limit", type=int, default=None, help="最多处理几个话题")
    parser.add_argument("--max-retries", type=int, default=10, help="单个话题最大重试次数")
    parser.add_argument("--retry-delay", type=int, default=5, help="重试间隔秒数")
    parser.add_argument("--sleep", type=int, default=None, help="话题之间固定休眠秒数")
    parser.add_argument(
        "--strategy",
        choices=[strategy.value for strategy in ArticleStrategy],
        default=None,
        help="覆盖所有话题的长文策略",
    )
    parser.add_argument("--no-publish", action="store_true", help="跳过发布（仅生成内容）")
    parser.add_argument("--no-image", action="store_true", help="跳过图片生成")
    parser.add_argument("--no-feishu", action="store_true", default=False, help="禁用飞书通知")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(run_batch(args)))


if __name__ == "__main__":
    main()
