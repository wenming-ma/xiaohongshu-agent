"""
执行 OutfitPostPipeline 完整工作流。

默认模式（feishu-only）：生成内容+图片后发送到飞书审核，不发布到小红书。
加 --publish 才会实际发布到小红书。

用法:
    # 默认：生成内容 → 发送飞书审核（不发布小红书）
    uv run python workshop/outfit_post/run.py

    # Mock 模式（跳过飞书讨论，用预设单品）
    uv run python workshop/outfit_post/run.py --mock

    # 实际发布到小红书
    uv run python workshop/outfit_post/run.py --publish

    # 指定范围
    uv run python workshop/outfit_post/run.py --start-index 2 --limit 1
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
    service_name='xiaohongshu-agent-outfit',
)
logfire.instrument_pydantic_ai()

from src.agents.outfit_post import OutfitPostPipeline  # noqa: E402
from src.agents.outfit_post.schemas import (  # noqa: E402
    OutfitPostInput,
    OutfitPostOutput,
    OutfitItem,
    ReferenceImageResult,
)
from src.config.settings import PathConfig  # noqa: E402
from src.utils.logger import get_logger, setup_logging  # noqa: E402
from src.utils.feishu_notifier import get_feishu_notifier  # noqa: E402
from src.utils.feishu_interactive_workflow import (  # noqa: E402
    acquire_interactive_session,
    finalize_interactive_session,
)
from src.utils.file_ops import save_json  # noqa: E402
from src.utils.feishu_sessions import SessionOwnershipError  # noqa: E402


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
        if not isinstance(item, dict) or not item.get("audience"):
            raise ValueError(f"第 {i} 项缺少 audience")
    return raw


# ---------------------------------------------------------------------------
# Feishu content review helper
# ---------------------------------------------------------------------------

FEISHU_MAX_TEXT_LEN = 3500


async def send_content_to_feishu(result: OutfitPostOutput, items_str: str) -> None:
    """将生成的完整内容（标题+正文+话题标签+图片）发送到飞书群审核。"""
    notifier = get_feishu_notifier()

    output_dir = Path(result.output_dir)
    content_file = output_dir / "content.json"
    full_body = ""
    if content_file.exists():
        content_data = json.loads(content_file.read_text(encoding="utf-8"))
        full_body = content_data.get("body") or ""

    title = result.title or items_str
    hashtags = " ".join(result.hashtags) if result.hashtags else "无"

    header = f"📋 穿搭帖内容审核\n单品：{items_str}\n标题：{title}\n话题：{hashtags}"

    if full_body and len(full_body) > FEISHU_MAX_TEXT_LEN:
        await notifier.send_message(header)
        for i in range(0, len(full_body), FEISHU_MAX_TEXT_LEN):
            chunk = full_body[i:i + FEISHU_MAX_TEXT_LEN]
            part_num = i // FEISHU_MAX_TEXT_LEN + 1
            await notifier.send_message(f"--- 正文 (第{part_num}段) ---\n{chunk}")
    else:
        body_section = f"\n---\n{full_body}" if full_body else ""
        await notifier.send_message(f"{header}{body_section}")

    image_paths = result.image_paths or []
    for idx, img_path in enumerate(image_paths, 1):
        p = Path(img_path)
        if p.exists():
            await notifier.send_image(p, caption=f"图片 {idx}/{len(image_paths)}")


# ---------------------------------------------------------------------------
# Mock 模式执行（跳过 DiscussAgent）
# ---------------------------------------------------------------------------

async def run_mock_single(
    item: dict[str, Any],
    publish: bool,
) -> OutfitPostOutput:
    """Mock 模式：直接用预设单品执行后续阶段"""
    from src.agents.outfit_post.research import ResearchAgent
    from src.agents.outfit_post.content import ContentAgent
    from src.agents.outfit_post.image import ImageAgent
    from src.agents.outfit_post.publish import PublisherAgent

    topic_hint = item.get("topic", "").strip()
    audience = item["audience"].strip()
    items_str = item.get("items", "").strip()

    if not items_str:
        return OutfitPostOutput(success=False, error_message="topics.json 中缺少 items 字段")

    item_names = [name.strip() for name in items_str.split(",") if name.strip()]
    outfit_items = [OutfitItem(name=name) for name in item_names]
    ref_images = ReferenceImageResult(skipped=True)

    search_names = item_names[:4]
    items_joined = "、".join(search_names)
    research_topic = f"{topic_hint}：{items_joined} 穿法搭配" if topic_hint else f"{items_joined} 穿搭穿法"

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_topic = "".join(c for c in (topic_hint or "outfit") if c.isalnum() or c in " -_")[:20]
    output_dir = PathConfig.IMAGE_PROJECT_DIR / f"{timestamp}-{safe_topic}-outfit"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[MOCK] 搭配单品: %s", ", ".join(item_names))
    logger.info("[MOCK] 研究主题: %s", research_topic)

    save_json(output_dir / "discuss.json", {
        "items": [i.model_dump() for i in outfit_items],
        "reference_images": ref_images.model_dump(),
        "research_topic": research_topic,
    })

    # Phase 2: 研究
    research_agent = ResearchAgent()
    research = await research_agent.forward(
        topic=research_topic, target_audience=audience, output_dir=output_dir,
    )
    save_json(output_dir / "research.json", research.model_dump())

    # Phase 3: 分组
    image_agent = ImageAgent()
    groups = await image_agent.compute_groups(
        research=research, topic=research_topic,
        ref_item_names=ref_images.get_item_names_with_images(),
    )
    save_json(output_dir / "groups.json", groups)

    # Phase 4: 内容
    content_agent = ContentAgent()
    content = await content_agent.forward(research=research, topic=research_topic, groups=groups)
    save_json(output_dir / "content.json", content.model_dump())

    # Phase 5: 图片
    image_result = await image_agent.forward(
        content=content, research=research, topic=research_topic,
        output_dir=output_dir, groups=groups, reference_images=ref_images,
    )
    save_json(output_dir / "image.json", image_result.model_dump())
    image_paths = [img.image_path for img in image_result.images]

    # Phase 6: 发布（仅当 --publish 时）
    publish_result = None
    if publish:
        publisher_agent = PublisherAgent()
        publish_result = await publisher_agent.forward(
            content=content, images=[Path(p) for p in image_paths], output_dir=output_dir,
        )
        save_json(output_dir / "publish.json", publish_result.model_dump())

    return OutfitPostOutput(
        success=True,
        title=content.title,
        body_preview=content.body[:200] if content.body else "",
        hashtags=content.hashtags,
        image_count=len(image_paths),
        image_paths=image_paths,
        published=publish_result.published if publish_result else False,
        post_url=publish_result.post_url if publish_result and publish_result.post_url else None,
        output_dir=str(output_dir),
    )


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
    publish: bool = False,
    mock: bool = False,
    notify_feishu: bool = True,
) -> dict[str, Any]:
    topic_hint = item.get("topic", "").strip()
    audience = item["audience"].strip()
    items_str = item.get("items", "").strip()

    logger.info("[%d/%d] 单品: %s", idx, total, items_str or "(飞书交互)")
    if topic_hint:
        logger.info("  风格提示: %s", topic_hint)
    logger.info("  受众: %s", audience)
    logger.info("  发布: %s", "小红书" if publish else "仅飞书审核")
    if mock:
        logger.info("  模式: MOCK")

    last_error = ""
    for attempt in range(1, max_retries + 1):
        session = None
        session_status = "cancelled"
        if attempt > 1:
            logger.warning("  重试 %d/%d，等待 %ds …", attempt, max_retries, retry_delay)
            await asyncio.sleep(retry_delay)

        try:
            if mock:
                result = await run_mock_single(item, publish=publish)
            else:
                notifier = get_feishu_notifier()
                session, blocked_reason = await acquire_interactive_session(
                    notifier=notifier,
                    workflow="outfit_post",
                    summary=topic_hint or audience,
                    current_phase="startup",
                )
                if blocked_reason:
                    return {
                        "success": False,
                        "run_status": "blocked",
                        "items": items_str,
                        "audience": audience,
                        "topic": topic_hint,
                        "error_message": blocked_reason,
                    }

                pipeline = OutfitPostPipeline(interactive_session=session)
                result = await pipeline.execute(
                    OutfitPostInput(topic=topic_hint, audience=audience, publish=publish)
                )
                session_status = "completed" if result.success else "cancelled"

            payload = result.model_dump()
            payload["topic"] = topic_hint
            payload["audience"] = audience
            payload["items"] = items_str
            payload["run_status"] = "success" if result.success else "failed"

            if result.success:
                logger.info("  成功: %s", result.title or items_str)

                if notify_feishu:
                    try:
                        if result.published:
                            # 发布成功通知
                            notifier = get_feishu_notifier()
                            lines = [
                                "✅ 穿搭帖子发布成功",
                                f"单品：{items_str}",
                                f"标题：{result.title or '无'}",
                                f"话题：{' '.join(result.hashtags) if result.hashtags else '无'}",
                                f"图片数：{result.image_count} 张",
                                f"帖子链接：{result.post_url or '未获取到'}",
                            ]
                            await notifier.send_message("\n".join(lines))
                            if result.image_paths:
                                await notifier.send_image(Path(result.image_paths[0]), caption="封面图")
                        else:
                            # 未发布 → 发送完整内容到飞书审核
                            await send_content_to_feishu(result, items_str)
                    except Exception:
                        logger.warning("飞书发送失败", exc_info=True)

                return payload

            last_error = result.error_message or "未知错误"
            logger.error("  失败: %s", last_error)
        except SessionOwnershipError as exc:
            return {
                "success": False,
                "run_status": "blocked",
                "items": items_str,
                "audience": audience,
                "topic": topic_hint,
                "error_message": str(exc),
            }
        except Exception:
            import traceback
            last_error = traceback.format_exc()
            logger.exception("  执行异常")
        finally:
            if not mock and session is not None:
                await finalize_interactive_session(session, status=session_status)

    return {"success": False, "run_status": "failed", "items": items_str, "audience": audience, "error_message": last_error}


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

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

    mode_label = "MOCK" if args.mock else "LIVE"
    publish_label = "发布到小红书" if args.publish else "仅飞书审核"

    logger.info("=" * 60)
    logger.info("XHS Outfit Post 批量执行 (%s / %s)", mode_label, publish_label)
    logger.info("话题文件: %s", args.topics_file)
    logger.info("范围: #%d ~ #%d (共 %d 个)", base_idx, base_idx + total - 1, total)
    logger.info("=" * 60)

    results: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, item in enumerate(selected):
        idx = base_idx + i
        result = await run_single(
            item, idx, base_idx + total - 1,
            args.max_retries, args.retry_delay,
            publish=args.publish,
            mock=args.mock,
            notify_feishu=not args.no_feishu,
        )
        results.append(result)

        if not result.get("success"):
            failed.append(result)

        if i < total - 1 and args.sleep is not None and args.sleep > 0:
            logger.info("休眠 %d 秒后继续 …", args.sleep)
            await asyncio.sleep(args.sleep)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = SCRIPT_DIR / f"outfit_post_summary_{ts}.json"
    summary = {
        "timestamp": ts,
        "total": total,
        "success": total - len(failed),
        "failed": len(failed),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("汇总文件: %s", summary_path)

    logger.info("=" * 60)
    logger.info("完成  成功: %d / %d  失败: %d / %d", total - len(failed), total, len(failed), total)
    logger.info("=" * 60)

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="执行 XHS Outfit Post 穿搭搭配帖子")
    p.add_argument("--topics-file", type=Path, default=SCRIPT_DIR / "topics.json", help="话题 JSON 文件")
    p.add_argument("--start-index", type=int, default=1, help="从第几个话题开始 (1-based)")
    p.add_argument("--limit", type=int, default=None, help="最多处理几个话题")
    p.add_argument("--max-retries", type=int, default=10, help="单个话题最大重试次数")
    p.add_argument("--retry-delay", type=int, default=5, help="重试间隔秒数")
    p.add_argument("--sleep", type=int, default=None, help="话题之间固定休眠秒数")
    p.add_argument("--mock", action="store_true", default=False, help="Mock 模式：跳过飞书讨论，使用 topics.json 预设单品")
    p.add_argument("--publish", action="store_true", default=False, help="发布到小红书（默认仅发送飞书审核）")
    p.add_argument("--no-feishu", action="store_true", default=False, help="禁用飞书发送")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(run_batch(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
