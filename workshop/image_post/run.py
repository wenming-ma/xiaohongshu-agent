"""
迭代执行 workshop/image_post/topics.json 中的话题，仅调用 XHSImagePostPipeline。

用法:
    uv run python workshop/image_post/run.py
    uv run python workshop/image_post/run.py --start-index 3
    uv run python workshop/image_post/run.py --start-index 5 --limit 2
    uv run python workshop/image_post/run.py --sleep 3600
    uv run python workshop/image_post/run.py --feishu-only
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
    send_to_logfire='if-token-present',
    environment='development',
    service_name='xiaohongshu-agent-batch',
)
logfire.instrument_pydantic_ai()

from src.agents.image_post import XHSImagePostInput, XHSImagePostPipeline  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402
from src.utils.feishu_notifier import get_feishu_notifier  # noqa: E402


def get_sleep_seconds(override: int | None) -> int:
    """根据当前时段返回休眠秒数。

    - 5:00-9:59 / 17:00-21:59 → 45 分钟 (2700s)
    - 其他时段 → 90 分钟 (5400s)
    - 如果 override 不为 None，则使用固定值
    """
    if override is not None:
        return override
    hour = datetime.now().hour
    if 5 <= hour < 10 or 17 <= hour < 22:
        return 2700  # 45 min
    return 5400  # 90 min

setup_logging()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Topics loading
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Feishu content review helper
# ---------------------------------------------------------------------------

FEISHU_MAX_TEXT_LEN = 3500


async def send_content_to_feishu(result: Any, topic: str) -> None:
    """将生成的完整内容（标题+正文+话题标签+图片）发送到飞书群审核。"""
    notifier = get_feishu_notifier()

    output_dir = Path(result.output_dir)
    content_file = output_dir / "content.json"
    full_body = ""
    if content_file.exists():
        content_data = json.loads(content_file.read_text(encoding="utf-8"))
        full_body = content_data.get("body") or ""

    title = result.title or topic
    hashtags = " ".join(result.hashtags) if result.hashtags else "无"

    header = f"📋 图文帖内容审核\n主题：{topic}\n标题：{title}\n话题：{hashtags}"

    if full_body and len(full_body) > FEISHU_MAX_TEXT_LEN:
        await notifier.send_message(header)
        for i in range(0, len(full_body), FEISHU_MAX_TEXT_LEN):
            chunk = full_body[i:i + FEISHU_MAX_TEXT_LEN]
            part_num = i // FEISHU_MAX_TEXT_LEN + 1
            await notifier.send_message(f"--- 正文 (第{part_num}段) ---\n{chunk}")
    else:
        body_section = f"\n---\n{full_body}" if full_body else ""
        await notifier.send_message(f"{header}{body_section}")

    image_paths = getattr(result, "image_paths", []) or []
    for idx, img_path in enumerate(image_paths, 1):
        p = Path(img_path)
        if p.exists():
            await notifier.send_image(p, caption=f"图片 {idx}/{len(image_paths)}")


def load_topics(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("topics.json 顶层必须是数组")
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or not item.get("topic") or not item.get("audience"):
            raise ValueError(f"第 {i} 项缺少 topic 或 audience")
    return raw


# ---------------------------------------------------------------------------
# Single topic execution
# ---------------------------------------------------------------------------

async def run_single(
    item: dict[str, Any],
    idx: int,
    total: int,
    max_retries: int,
    retry_delay: int,
    *,
    publish: bool = True,
    notify_feishu: bool = True,
) -> dict[str, Any]:
    topic = item["topic"].strip()
    audience = item["audience"].strip()

    logger.info("[%d/%d] 话题: %s", idx, total, topic)
    logger.info("  受众: %s", audience)
    logger.info("  发布: %s", publish)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.warning("  重试 %d/%d，等待 %ds …", attempt, max_retries, retry_delay)
            await asyncio.sleep(retry_delay)

        try:
            tool = XHSImagePostPipeline()
            result = await tool.execute(XHSImagePostInput(topic=topic, audience=audience, publish=publish))
            payload = result.model_dump()
            payload["topic"] = topic
            payload["audience"] = audience

            if result.success:
                logger.info("  成功: %s", result.title or topic)

                # 飞书通知
                if result.published and notify_feishu:
                    try:
                        notifier = get_feishu_notifier()
                        lines = [
                            "✅ 帖子发布成功",
                            f"主题：{topic}",
                            f"标题：{result.title or '无'}",
                            f"话题：{' '.join(result.hashtags) if result.hashtags else '无'}",
                            f"图片数：{result.image_count} 张",
                            f"帖子链接：{result.post_url or '未获取到'}",
                        ]
                        await notifier.send_message("\n".join(lines))
                        # 发送封面图预览
                        if result.image_paths:
                            await notifier.send_image(Path(result.image_paths[0]), caption="封面图")
                    except Exception:
                        logger.warning("飞书通知发送失败", exc_info=True)
                elif not publish:
                    try:
                        await send_content_to_feishu(result, topic)
                    except Exception:
                        logger.warning("飞书内容审核发送失败", exc_info=True)

                return payload

            last_error = result.error_message or "未知错误"
            logger.error("  失败: %s", last_error)
        except Exception:
            import traceback
            last_error = traceback.format_exc()
            logger.exception("  执行异常")

    return {"success": False, "topic": topic, "audience": audience, "error_message": last_error}


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

async def run_batch(args: argparse.Namespace) -> int:
    topics = load_topics(args.topics_file)

    # 切片: start_index 是 1-based
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
    logger.info("XHS Image Post 批量执行")
    logger.info("话题文件: %s", args.topics_file)
    logger.info("范围: #%d ~ #%d (共 %d 个)", base_idx, base_idx + total - 1, total)
    sleep_mode = f"固定 {args.sleep}s" if args.sleep is not None else "不休眠"
    logger.info("最大重试: %d  重试间隔: %ds  休眠策略: %s", args.max_retries, args.retry_delay, sleep_mode)
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, item in enumerate(selected):
        idx = base_idx + i
        result = await run_single(
            item, idx, base_idx + total - 1,
            args.max_retries, args.retry_delay,
            publish=not args.feishu_only,
            notify_feishu=not args.no_feishu,
        )
        results.append(result)

        if not result.get("success"):
            failed.append(result)

        # 话题间休眠（仅当通过 --sleep 显式指定时才休眠）
        if i < total - 1 and args.sleep is not None and args.sleep > 0:
            logger.info("休眠 %d 秒 (%.0f 分钟) 后继续 …", args.sleep, args.sleep / 60)
            await asyncio.sleep(args.sleep)

    # 写出汇总
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = SCRIPT_DIR / f"image_post_summary_{ts}.json"
    summary = {
        "timestamp": ts,
        "total": total,
        "success": total - len(failed),
        "failed": len(failed),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("汇总文件: %s", summary_path)

    if failed:
        failed_path = SCRIPT_DIR / f"image_post_failed_{ts}.json"
        failed_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("失败列表: %s", failed_path)

    logger.info("=" * 60)
    logger.info("完成  成功: %d / %d  失败: %d / %d", total - len(failed), total, len(failed), total)
    logger.info("=" * 60)

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="批量执行 XHS Image Post（仅 image_post agent）")
    p.add_argument("--topics-file", type=Path, default=SCRIPT_DIR / "topics.json", help="话题 JSON 文件")
    p.add_argument("--start-index", type=int, default=1, help="从第几个话题开始 (1-based)")
    p.add_argument("--limit", type=int, default=None, help="最多处理几个话题")
    p.add_argument("--max-retries", type=int, default=10, help="单个话题最大重试次数")
    p.add_argument("--retry-delay", type=int, default=5, help="重试间隔秒数")
    p.add_argument("--sleep", type=int, default=None, help="话题之间固定休眠秒数 (留空则不休眠)")
    p.add_argument("--no-feishu", action="store_true", default=False, help="禁用飞书通知")
    p.add_argument("--feishu-only", action="store_true", help="跳过 XHS 发布，仅生成内容并发送到飞书审核")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run_batch(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
