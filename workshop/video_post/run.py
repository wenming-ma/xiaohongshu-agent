"""
迭代执行 workshop/video_post/topics.json 中的话题，仅调用 XHSVideoPostPipeline。

用法:
    uv run python workshop/video_post/run.py
    uv run python workshop/video_post/run.py --start-index 2
    uv run python workshop/video_post/run.py --limit 1 --no-publish
    uv run python workshop/video_post/run.py --platforms tiktok instagram --max-videos 3
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import traceback
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
    service_name="xiaohongshu-agent-video-batch",
)
logfire.instrument_pydantic_ai()

from src.agents.video_post import XHSVideoPostInput, XHSVideoPostPipeline  # noqa: E402
from src.agents.video_post.schemas import Platform  # noqa: E402
from src.utils.feishu_notifier import get_feishu_notifier  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402

setup_logging()
logger = get_logger(__name__)

PLATFORM_CHOICES = [p.value for p in Platform]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_topics(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("topics.json 顶层必须是数组")
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or not item.get("topic") or not item.get("audience"):
            raise ValueError(f"第 {i} 项缺少 topic 或 audience")
    return raw


def resolve_platforms(item: dict[str, Any], override: list[str] | None) -> list[Platform]:
    if override:
        return [Platform(p) for p in override]
    raw = item.get("platforms")
    if isinstance(raw, list) and raw:
        return [Platform(p) for p in raw]
    return list(Platform)


async def run_single(
    item: dict[str, Any],
    idx: int,
    total: int,
    *,
    max_retries: int,
    retry_delay: int,
    publish: bool,
    max_videos: int | None,
    platforms_override: list[str] | None,
    notify_feishu: bool = True,
) -> dict[str, Any]:
    topic = item["topic"].strip()
    audience = item["audience"].strip()
    platforms = resolve_platforms(item, platforms_override)
    videos = max_videos or item.get("max_videos") or 5

    logger.info("[%d/%d] 话题: %s", idx, total, topic)
    logger.info("  受众: %s", audience)
    logger.info("  平台: %s", [p.value for p in platforms])
    logger.info("  最大视频数: %d  发布: %s", videos, publish)

    last_error = ""
    last_output_dir = ""
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.warning("  重试 %d/%d，等待 %ds …", attempt, max_retries, retry_delay)
            await asyncio.sleep(retry_delay)

        try:
            pipeline = XHSVideoPostPipeline()
            result = await pipeline.execute(
                XHSVideoPostInput(
                    topic=topic,
                    audience=audience,
                    platforms=platforms,
                    max_videos=videos,
                    publish=publish,
                )
            )
            last_output_dir = result.output_dir or ""
            payload = result.model_dump()
            payload["topic"] = topic
            payload["audience"] = audience
            payload["attempts"] = attempt

            if result.success:
                logger.info("  成功: %s", result.title or topic)
                logger.info("  输出目录: %s", result.output_dir)

                if result.published and notify_feishu:
                    try:
                        notifier = get_feishu_notifier()
                        lines = [
                            "✅ 视频发布成功",
                            f"主题：{topic}",
                            f"标题：{result.title or '无'}",
                            f"话题：{' '.join(result.hashtags) if result.hashtags else '无'}",
                            f"视频：{result.video_path or '无'}",
                            f"帖子链接：{result.post_url or '未获取到'}",
                        ]
                        await notifier.send_message("\n".join(lines))
                    except Exception:
                        logger.warning("飞书通知发送失败", exc_info=True)

                return payload

            last_error = result.error_message or "未知错误"
            logger.error("  失败: %s", last_error)
        except Exception:
            last_error = traceback.format_exc()
            logger.exception("  执行异常")

    return {
        "success": False,
        "topic": topic,
        "audience": audience,
        "error_message": last_error,
        "attempts": max_retries,
        "output_dir": last_output_dir,
    }


async def run_batch(args: argparse.Namespace) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = SCRIPT_DIR / f"video_post_summary_{ts}.json"
    failed_path = SCRIPT_DIR / f"video_post_failed_{ts}.json"
    failed_stream_path = SCRIPT_DIR / f"video_post_failures_{ts}.jsonl"
    crash_path = SCRIPT_DIR / f"video_post_crash_{ts}.json"
    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    total = 0
    selected: list[dict[str, Any]] = []
    base_idx = args.start_index
    try:
        topics = load_topics(args.topics_file)

        start = args.start_index - 1
        selected = topics[start:]
        if args.limit is not None:
            selected = selected[: args.limit]

        if not selected:
            logger.warning("没有可处理的话题")
            return 0

        total = len(selected)

        logger.info("=" * 60)
        logger.info("XHS Video Post 批量执行")
        logger.info("运行批次: %s", ts)
        logger.info("话题文件: %s", args.topics_file)
        logger.info("范围: #%d ~ #%d (共 %d 个)", base_idx, base_idx + total - 1, total)
        logger.info(
            "最大重试: %d  重试间隔: %ds  发布: %s",
            args.max_retries,
            args.retry_delay,
            not args.no_publish,
        )
        if args.platforms:
            logger.info("平台覆盖: %s", args.platforms)
        if args.max_videos:
            logger.info("最大视频数覆盖: %d", args.max_videos)
        logger.info("失败实时日志: %s", failed_stream_path)
        logger.info("=" * 60)

        for i, item in enumerate(selected):
            idx = base_idx + i
            result = await run_single(
                item,
                idx,
                base_idx + total - 1,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                publish=not args.no_publish,
                max_videos=args.max_videos,
                platforms_override=args.platforms,
                notify_feishu=not args.no_feishu,
            )
            results.append(result)

            if not result.get("success"):
                failed.append(result)
                append_jsonl(
                    failed_stream_path,
                    {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "index": idx,
                        "topic": result.get("topic", ""),
                        "audience": result.get("audience", ""),
                        "error_message": result.get("error_message", ""),
                        "attempts": result.get("attempts", args.max_retries),
                        "output_dir": result.get("output_dir", ""),
                    },
                )
                logger.warning("失败已记录: %s", failed_stream_path)

            if i < total - 1 and args.sleep is not None and args.sleep > 0:
                logger.info("休眠 %d 秒 (%.0f 分钟) 后继续 …", args.sleep, args.sleep / 60)
                await asyncio.sleep(args.sleep)

        summary = {
            "timestamp": ts,
            "status": "completed",
            "publish": not args.no_publish,
            "total": total,
            "success": total - len(failed),
            "failed": len(failed),
            "results": results,
        }
        write_json(summary_path, summary)
        logger.info("汇总文件: %s", summary_path)

        if failed:
            write_json(failed_path, {"timestamp": ts, "count": len(failed), "items": failed})
            logger.warning("失败列表: %s", failed_path)
            logger.warning("失败实时日志: %s", failed_stream_path)

        logger.info("=" * 60)
        logger.info("完成  成功: %d / %d  失败: %d / %d", total - len(failed), total, len(failed), total)
        logger.info("=" * 60)

        return 1 if failed else 0
    except Exception:
        crash_summary = {
            "timestamp": ts,
            "status": "crashed",
            "publish": not args.no_publish,
            "total": total,
            "success": len([r for r in results if r.get("success")]),
            "failed": len(failed),
            "processed": len(results),
            "results": results,
        }
        write_json(summary_path, crash_summary)
        write_json(
            crash_path,
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "batch": ts,
                "error": traceback.format_exc(),
                "topics_file": str(args.topics_file),
                "summary_path": str(summary_path),
                "failed_stream_path": str(failed_stream_path),
            },
        )
        logger.exception("批量执行异常中断")
        logger.error("崩溃日志: %s", crash_path)
        logger.error("部分汇总: %s", summary_path)
        return 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量执行 XHS Video Post")
    parser.add_argument("--topics-file", type=Path, default=SCRIPT_DIR / "topics.json", help="话题 JSON 文件")
    parser.add_argument("--start-index", type=int, default=1, help="从第几个话题开始 (1-based)")
    parser.add_argument("--limit", type=int, default=None, help="最多处理几个话题")
    parser.add_argument("--max-retries", type=int, default=10, help="单个话题最大重试次数")
    parser.add_argument("--retry-delay", type=int, default=5, help="重试间隔秒数")
    parser.add_argument("--sleep", type=int, default=None, help="话题之间固定休眠秒数")
    parser.add_argument("--platforms", nargs="+", choices=PLATFORM_CHOICES, default=None, help="覆盖搜索平台")
    parser.add_argument("--max-videos", type=int, default=None, help="覆盖最大视频数")
    parser.add_argument("--no-publish", action="store_true", help="跳过发布（仅搜索下载和生成内容）")
    parser.add_argument("--no-feishu", action="store_true", default=False, help="禁用飞书通知")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    code = asyncio.run(run_batch(args))
    import os
    os._exit(code)


if __name__ == "__main__":
    main()
