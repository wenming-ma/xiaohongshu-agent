"""
交替执行 image post 和 article post：每发布 3 个 image post 后发布 1 个 article post。

从 image_post/topics.json 和 article_post/topics.json 分别读取话题队列，
按 3:1 的顺序交替消费，直到两个队列都耗尽。

用法:
    uv run python workshop/mixed/run.py
    uv run python workshop/mixed/run.py --start-image 4 --start-article 2
    uv run python workshop/mixed/run.py --image-limit 6 --article-limit 2
    uv run python workshop/mixed/run.py --sleep 1800
    uv run python workshop/mixed/run.py --no-publish
    uv run python workshop/mixed/run.py --feishu-only
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
    service_name="xiaohongshu-agent-mixed-batch",
)
logfire.instrument_pydantic_ai()

from src.agents.image_post import XHSImagePostInput, XHSImagePostPipeline  # noqa: E402
from src.agents.article_post import XHSArticlePostInput, XHSArticlePostPipeline  # noqa: E402
from src.agents.article_post.schemas import ArticleStrategy  # noqa: E402
from src.utils.feishu_notifier import get_feishu_notifier  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)

IMAGE_PER_CYCLE = 3


# ---------------------------------------------------------------------------
# Topics loading
# ---------------------------------------------------------------------------

def load_topics(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} 顶层必须是数组")
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or not item.get("topic") or not item.get("audience"):
            raise ValueError(f"{path.name} 第 {i} 项缺少 topic 或 audience")
    return raw


# ---------------------------------------------------------------------------
# Sleep helper
# ---------------------------------------------------------------------------

WORK_START_HOUR = 2   # 凌晨 2 点开始工作
WORK_END_HOUR = 10    # 早上 10 点开始休眠
POST_INTERVAL = 1500  # 发帖间隔 25 分钟 (25 * 60)


def is_work_hours() -> bool:
    """判断当前是否在工作时段 (2:00 - 9:59)"""
    return WORK_START_HOUR <= datetime.now().hour < WORK_END_HOUR


def seconds_until_work_start() -> int:
    """计算距离下一个工作时段开始的秒数"""
    now = datetime.now()
    if now.hour < WORK_START_HOUR:
        # 今天还没到工作时间
        wake_up = now.replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
    else:
        # 已过今天的工作时间，等明天
        from datetime import timedelta
        wake_up = (now + timedelta(days=1)).replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
    return int((wake_up - now).total_seconds())


def get_sleep_seconds(override: int | None) -> int:
    """根据当前时段返回休眠秒数。

    - 2:00-9:59 → 25 分钟 (1500s)
    - 10:00-1:59 → 休眠到次日 2:00
    - 如果 override 不为 None，则使用固定值
    """
    if override is not None:
        return override
    if not is_work_hours():
        return seconds_until_work_start()
    return POST_INTERVAL


# ---------------------------------------------------------------------------
# Feishu content review helper
# ---------------------------------------------------------------------------

FEISHU_MAX_TEXT_LEN = 3500


async def send_content_to_feishu(result: Any, post_type: str, topic: str) -> None:
    """将生成的完整内容（标题+正文+话题标签+图片）发送到飞书群审核。"""
    notifier = get_feishu_notifier()

    # 从 output_dir/content.json 读取完整正文
    output_dir = Path(result.output_dir)
    content_file = output_dir / "content.json"
    full_body = ""
    if content_file.exists():
        content_data = json.loads(content_file.read_text(encoding="utf-8"))
        # 图文帖用 body，长文用 rendered_body
        full_body = content_data.get("rendered_body") or content_data.get("body") or ""

    title = result.title or topic
    hashtags = " ".join(result.hashtags) if result.hashtags else "无"
    type_label = "图文帖" if post_type == "image" else "长文"

    # 构建文本消息
    header = f"📋 {type_label}内容审核\n主题：{topic}\n标题：{title}\n话题：{hashtags}"

    if full_body and len(full_body) > FEISHU_MAX_TEXT_LEN:
        # 正文过长，分段发送
        await notifier.send_message(header)
        # 分段发送正文
        for i in range(0, len(full_body), FEISHU_MAX_TEXT_LEN):
            chunk = full_body[i:i + FEISHU_MAX_TEXT_LEN]
            part_num = i // FEISHU_MAX_TEXT_LEN + 1
            await notifier.send_message(f"--- 正文 (第{part_num}段) ---\n{chunk}")
    else:
        body_section = f"\n---\n{full_body}" if full_body else ""
        await notifier.send_message(f"{header}{body_section}")

    # 逐张发送图片
    image_paths = getattr(result, "image_paths", []) or []
    for idx, img_path in enumerate(image_paths, 1):
        p = Path(img_path)
        if p.exists():
            await notifier.send_image(p, caption=f"图片 {idx}/{len(image_paths)}")


# ---------------------------------------------------------------------------
# Single post execution
# ---------------------------------------------------------------------------

async def run_image_post(
    item: dict[str, Any],
    idx: int,
    label: str,
    *,
    max_retries: int,
    retry_delay: int,
    publish: bool,
) -> dict[str, Any]:
    topic = item["topic"].strip()
    audience = item["audience"].strip()

    logger.info("[%s] 📷 Image Post | 话题: %s", label, topic)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.warning("  重试 %d/%d，等待 %ds …", attempt, max_retries, retry_delay)
            await asyncio.sleep(retry_delay)
        try:
            tool = XHSImagePostPipeline()
            result = await tool.execute(XHSImagePostInput(topic=topic, audience=audience, publish=publish))
            payload = result.model_dump()
            payload["post_type"] = "image"
            payload["topic"] = topic
            payload["audience"] = audience

            if result.success:
                logger.info("  成功: %s", result.title or topic)
                if result.published:
                    try:
                        notifier = get_feishu_notifier()
                        lines = [
                            "✅ 图文帖发布成功",
                            f"主题：{topic}",
                            f"标题：{result.title or '无'}",
                            f"话题：{' '.join(result.hashtags) if result.hashtags else '无'}",
                            f"图片数：{result.image_count} 张",
                            f"帖子链接：{result.post_url or '未获取到'}",
                        ]
                        await notifier.send_message("\n".join(lines))
                        if result.image_paths:
                            await notifier.send_image(Path(result.image_paths[0]), caption="封面图")
                    except Exception:
                        logger.warning("飞书通知发送失败", exc_info=True)
                elif not publish:
                    try:
                        await send_content_to_feishu(result, "image", topic)
                    except Exception:
                        logger.warning("飞书内容审核发送失败", exc_info=True)
                return payload

            last_error = result.error_message or "未知错误"
            logger.error("  失败: %s", last_error)
        except Exception:
            import traceback
            last_error = traceback.format_exc()
            logger.exception("  执行异常")

    return {"success": False, "post_type": "image", "topic": topic, "audience": audience, "error_message": last_error}


async def run_article_post(
    item: dict[str, Any],
    idx: int,
    label: str,
    *,
    max_retries: int,
    retry_delay: int,
    publish: bool,
    strategy_override: str | None,
) -> dict[str, Any]:
    topic = item["topic"].strip()
    audience = item["audience"].strip()

    # Resolve strategy
    if strategy_override:
        strategy = ArticleStrategy(strategy_override)
    else:
        raw = str(item.get("strategy") or "").strip()
        strategy = ArticleStrategy(raw) if raw in {s.value for s in ArticleStrategy} else ArticleStrategy.AUTO

    logger.info("[%s] 📝 Article Post | 话题: %s | 策略: %s", label, topic, strategy.value)

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
                    strategy=strategy,
                )
            )
            payload = result.model_dump()
            payload["post_type"] = "article"
            payload["topic"] = topic
            payload["audience"] = audience
            payload["strategy"] = strategy.value

            if result.success:
                logger.info("  成功: %s", result.title or topic)
                if result.published:
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
                elif not publish:
                    try:
                        await send_content_to_feishu(result, "article", topic)
                    except Exception:
                        logger.warning("飞书内容审核发送失败", exc_info=True)
                return payload

            last_error = result.error_message or "未知错误"
            logger.error("  失败: %s", last_error)
        except Exception:
            import traceback
            last_error = traceback.format_exc()
            logger.exception("  执行异常")

    return {
        "success": False,
        "post_type": "article",
        "topic": topic,
        "audience": audience,
        "strategy": strategy.value,
        "error_message": last_error,
    }


# ---------------------------------------------------------------------------
# Build interleaved schedule
# ---------------------------------------------------------------------------

def build_schedule(
    image_topics: list[dict[str, Any]],
    article_topics: list[dict[str, Any]],
) -> list[tuple[str, int, dict[str, Any]]]:
    """Build an interleaved schedule: 3 image posts then 1 article post, repeat.

    Returns list of (post_type, 1-based-index-within-type, topic_item).
    Continues until both queues are exhausted.
    """
    schedule: list[tuple[str, int, dict[str, Any]]] = []
    img_idx = 0
    art_idx = 0

    while img_idx < len(image_topics) or art_idx < len(article_topics):
        # Take up to IMAGE_PER_CYCLE image posts first
        for _ in range(IMAGE_PER_CYCLE):
            if img_idx < len(image_topics):
                schedule.append(("image", img_idx + 1, image_topics[img_idx]))
                img_idx += 1

        # Then take 1 article post
        if art_idx < len(article_topics):
            schedule.append(("article", art_idx + 1, article_topics[art_idx]))
            art_idx += 1

    return schedule


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

async def run_batch(args: argparse.Namespace) -> int:
    image_topics = load_topics(args.image_topics_file)
    article_topics = load_topics(args.article_topics_file)

    # Slice each queue
    image_selected = image_topics[args.start_image - 1:]
    if args.image_limit is not None:
        image_selected = image_selected[:args.image_limit]

    article_selected = article_topics[args.start_article - 1:]
    if args.article_limit is not None:
        article_selected = article_selected[:args.article_limit]

    if not image_selected and not article_selected:
        logger.warning("没有可处理的话题")
        return 0

    schedule = build_schedule(image_selected, article_selected)
    total = len(schedule)

    logger.info("=" * 60)
    logger.info("XHS Mixed Post 批量执行 (3 image -> 1 article)")
    logger.info("图文话题: %s (第 %d 项起, 共 %d 个)", args.image_topics_file.name, args.start_image, len(image_selected))
    logger.info("长文话题: %s (第 %d 项起, 共 %d 个)", args.article_topics_file.name, args.start_article, len(article_selected))
    logger.info("调度总数: %d 个帖子", total)
    sleep_mode = f"固定 {args.sleep}s" if args.sleep is not None else "动态 (2-10点=25min, 10-2点=休眠)"
    logger.info("休眠策略: %s", sleep_mode)
    if args.feishu_only:
        logger.info("运行模式: 飞书审核 (跳过 XHS 发布，内容发送到飞书)")
    logger.info("长文发布: %s  策略覆盖: %s", not args.no_publish and not args.feishu_only, args.strategy or "无")
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, (post_type, type_idx, item) in enumerate(schedule):
        label = f"{i + 1}/{total}"

        if post_type == "image":
            result = await run_image_post(
                item, type_idx, label,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                publish=not args.feishu_only,
            )
        else:
            result = await run_article_post(
                item, type_idx, label,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                publish=not args.no_publish and not args.feishu_only,
                strategy_override=args.strategy,
            )

        results.append(result)
        if not result.get("success"):
            failed.append(result)

        # Sleep between posts
        if i < total - 1:
            sleep_s = get_sleep_seconds(args.sleep)
            if sleep_s > 0:
                logger.info("休眠 %d 秒 (%.0f 分钟) 后继续 …", sleep_s, sleep_s / 60)
                await asyncio.sleep(sleep_s)

    # Write summary
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = SCRIPT_DIR / f"mixed_post_summary_{ts}.json"
    image_count = sum(1 for r in results if r.get("post_type") == "image")
    article_count = sum(1 for r in results if r.get("post_type") == "article")
    summary = {
        "timestamp": ts,
        "total": total,
        "image_posts": image_count,
        "article_posts": article_count,
        "success": total - len(failed),
        "failed": len(failed),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("汇总文件: %s", summary_path)

    if failed:
        failed_path = SCRIPT_DIR / f"mixed_post_failed_{ts}.json"
        failed_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("失败列表: %s", failed_path)

    logger.info("=" * 60)
    logger.info(
        "完成  总计: %d (图文 %d + 长文 %d)  成功: %d  失败: %d",
        total, image_count, article_count, total - len(failed), len(failed),
    )
    logger.info("=" * 60)

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="交替批量执行 XHS 图文帖和长文帖 (3 图文 -> 1 长文)",
    )

    # Topic files
    p.add_argument("--image-topics-file", type=Path, default=SCRIPT_DIR.parent / "image_post" / "topics.json", help="图文话题 JSON 文件")
    p.add_argument("--article-topics-file", type=Path, default=SCRIPT_DIR.parent / "article_post" / "topics.json", help="长文话题 JSON 文件")

    # Range control
    p.add_argument("--start-image", type=int, default=1, help="图文话题从第几个开始 (1-based)")
    p.add_argument("--start-article", type=int, default=1, help="长文话题从第几个开始 (1-based)")
    p.add_argument("--image-limit", type=int, default=None, help="最多处理几个图文话题")
    p.add_argument("--article-limit", type=int, default=None, help="最多处理几个长文话题")

    # Retry & sleep
    p.add_argument("--max-retries", type=int, default=10, help="单个话题最大重试次数")
    p.add_argument("--retry-delay", type=int, default=5, help="重试间隔秒数")
    p.add_argument("--sleep", type=int, default=None, help="帖子之间固定休眠秒数 (留空则按时段自动)")

    # Article-specific
    p.add_argument(
        "--strategy",
        choices=[s.value for s in ArticleStrategy],
        default=None,
        help="覆盖所有长文的策略",
    )
    p.add_argument("--no-publish", action="store_true", help="长文不发布（仅生成）")
    p.add_argument("--feishu-only", action="store_true",
                   help="跳过 XHS 发布，仅生成内容并发送到飞书审核")

    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(run_batch(args)))


if __name__ == "__main__":
    main()
