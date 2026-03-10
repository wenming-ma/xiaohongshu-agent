"""Batch-generate Xiaohongshu image posts from workshop/topics.json."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

load_dotenv(PROJECT_ROOT / ".env")

import logfire
from src.utils.logfire_telegram_handler import TelegramSpanProcessor

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

from src.tools.xiaohongshu.image_post import XHSImagePostInput, XHSImagePostTool
from src.utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(description="批量生成小红书图文内容")
    parser.add_argument(
        "--topics-file",
        type=Path,
        default=script_dir / "topics.json",
        help="topics.json 文件路径",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=10,
        help="单个主题最大重试次数",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=int,
        default=5,
        help="重试间隔秒数",
    )
    parser.add_argument(
        "--sleep-between-topics-seconds",
        type=int,
        default=5400,
        help="主题之间休眠秒数",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="从第几个主题开始，1-based",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最多处理多少个主题",
    )
    return parser.parse_args()


def load_topics(json_path: Path) -> list[dict[str, Any]]:
    if not json_path.exists():
        raise FileNotFoundError(f"topics.json 不存在: {json_path}")

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("topics.json 顶层必须是数组")

    topics: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项必须是对象")

        topic = str(item.get("topic", "")).strip()
        audience = str(item.get("audience", "")).strip()
        if not topic or not audience:
            raise ValueError(f"第 {index} 项缺少 topic 或 audience")

        topics.append(item)

    return topics


def select_topics(topics: list[dict[str, Any]], start_index: int, limit: int | None) -> list[dict[str, Any]]:
    if start_index < 1:
        raise ValueError("--start-index 必须大于等于 1")

    start_offset = start_index - 1
    selected = topics[start_offset:]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit 必须大于等于 1")
        selected = selected[:limit]
    return selected


async def run_single_topic(
    item: dict[str, Any],
    topic_number: int,
    total_count: int,
    max_retries: int,
    retry_delay_seconds: int,
) -> dict[str, Any]:
    topic = str(item["topic"]).strip()
    audience = str(item["audience"]).strip()
    strategy = str(item.get("strategy", "")).strip()

    logger.info("[%d/%d] %s", topic_number, total_count, topic)
    logger.info("受众: %s", audience)
    if strategy:
        logger.info("策略备注: %s", strategy)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.warning("重试 %d/%d，等待 %d 秒", attempt, max_retries, retry_delay_seconds)
            await asyncio.sleep(retry_delay_seconds)

        try:
            tool = XHSImagePostTool()
            result = await tool.execute(
                XHSImagePostInput(
                    topic=topic,
                    audience=audience,
                )
            )
            payload = result.model_dump()
            payload["topic"] = topic
            payload["audience"] = audience
            if strategy:
                payload["strategy"] = strategy

            if result.success:
                logger.info("成功: %s", result.title or topic)
                if result.output_dir:
                    logger.info("输出目录: %s", result.output_dir)
                return payload

            last_error = result.error_message or "未知错误"
            logger.error("失败: %s", last_error)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            logger.exception("执行异常")

    return {
        "success": False,
        "topic": topic,
        "audience": audience,
        "strategy": strategy,
        "error_message": last_error or "达到最大重试次数",
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_batch(args: argparse.Namespace) -> int:
    if args.max_retries < 1:
        raise ValueError("--max-retries 必须大于等于 1")
    if args.retry_delay_seconds < 0:
        raise ValueError("--retry-delay-seconds 不能小于 0")
    if args.sleep_between_topics_seconds < 0:
        raise ValueError("--sleep-between-topics-seconds 不能小于 0")

    topics = load_topics(args.topics_file)
    selected_topics = select_topics(topics, args.start_index, args.limit)

    if not selected_topics:
        logger.warning("没有可处理的主题")
        return 0

    script_dir = Path(__file__).resolve().parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = script_dir / f"batch_summary_{timestamp}.json"
    failed_path = script_dir / f"failed_topics_{timestamp}.json"

    logger.info("=" * 60)
    logger.info("Xiaohongshu Image Post Batch Generation")
    logger.info("topics file: %s", args.topics_file)
    logger.info("selected topics: %d", len(selected_topics))
    logger.info("max retries: %d", args.max_retries)
    logger.info("sleep between topics: %d seconds", args.sleep_between_topics_seconds)
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    failed_topics: list[dict[str, Any]] = []

    for index, item in enumerate(selected_topics, start=args.start_index):
        result = await run_single_topic(
            item=item,
            topic_number=index,
            total_count=args.start_index + len(selected_topics) - 1,
            max_retries=args.max_retries,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        results.append(result)

        if not result.get("success"):
            failed_topics.append(result)

        if index < args.start_index + len(selected_topics) - 1 and args.sleep_between_topics_seconds > 0:
            logger.info("休眠 %d 秒后处理下一个主题", args.sleep_between_topics_seconds)
            await asyncio.sleep(args.sleep_between_topics_seconds)

    summary = {
        "topics_file": str(args.topics_file),
        "processed_count": len(selected_topics),
        "success_count": len(selected_topics) - len(failed_topics),
        "failed_count": len(failed_topics),
        "results": results,
    }
    write_json(summary_path, summary)
    if failed_topics:
        write_json(failed_path, failed_topics)

    logger.info("=" * 60)
    logger.info("批量生成完成")
    logger.info("成功: %d / %d", summary["success_count"], len(selected_topics))
    logger.info("失败: %d / %d", summary["failed_count"], len(selected_topics))
    logger.info("汇总文件: %s", summary_path)
    if failed_topics:
        logger.warning("失败列表: %s", failed_path)
    logger.info("=" * 60)

    return 1 if failed_topics else 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run_batch(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
