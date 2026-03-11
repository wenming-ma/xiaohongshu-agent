"""
迭代执行 workshop/topics.json 中的话题，仅调用 XHSImagePostTool。

用法:
    uv run python workshop/run_image_posts.py
    uv run python workshop/run_image_posts.py --start-index 3
    uv run python workshop/run_image_posts.py --start-index 5 --limit 2
    uv run python workshop/run_image_posts.py --sleep 3600
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")

import logfire  # noqa: E402
from src.utils.logfire_telegram_handler import TelegramSpanProcessor  # noqa: E402

logfire.configure(
    send_to_logfire='if-token-present',
    environment='development',
    service_name='xiaohongshu-agent-batch',
    additional_span_processors=[
        TelegramSpanProcessor(
            min_interval_sec=1.0,
            include_http_requests=False,
            include_tool_args=True,
            max_arg_length=200,
        ),
    ],
)
logfire.instrument_pydantic_ai()

from src.tools.xiaohongshu.image_post import XHSImagePostInput, XHSImagePostTool  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402


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
) -> dict[str, Any]:
    topic = item["topic"].strip()
    audience = item["audience"].strip()

    logger.info("[%d/%d] 话题: %s", idx, total, topic)
    logger.info("  受众: %s", audience)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.warning("  重试 %d/%d，等待 %ds …", attempt, max_retries, retry_delay)
            await asyncio.sleep(retry_delay)

        try:
            tool = XHSImagePostTool()
            result = await tool.execute(XHSImagePostInput(topic=topic, audience=audience))
            payload = result.model_dump()
            payload["topic"] = topic
            payload["audience"] = audience

            if result.success:
                logger.info("  成功: %s", result.title or topic)
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
    sleep_mode = f"固定 {args.sleep}s" if args.sleep is not None else "动态 (5-10/17-22点=45min, 其余=90min)"
    logger.info("最大重试: %d  重试间隔: %ds  休眠策略: %s", args.max_retries, args.retry_delay, sleep_mode)
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, item in enumerate(selected):
        idx = base_idx + i
        result = await run_single(item, idx, base_idx + total - 1, args.max_retries, args.retry_delay)
        results.append(result)

        if not result.get("success"):
            failed.append(result)

        # 话题间休眠（最后一个不休眠）
        if i < total - 1:
            sleep_sec = get_sleep_seconds(args.sleep)
            if sleep_sec > 0:
                logger.info("休眠 %d 秒 (%.0f 分钟) 后继续 …", sleep_sec, sleep_sec / 60)
                await asyncio.sleep(sleep_sec)

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
    p.add_argument("--sleep", type=int, default=None, help="话题之间固定休眠秒数 (留空则按时段自动: 5-10点/17-22点=45min, 其余=90min)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run_batch(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
