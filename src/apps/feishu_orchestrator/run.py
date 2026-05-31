from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent

FEISHU_INTERACTIVE_ENV_DEFAULTS = {
    "RESEARCH_MIN_POSTS_RESEARCHED": "3",
    "RESEARCH_VALIDATION_MAX_RETRIES": "3",
    "VERTEX_AI_VISION_MAX_CONCURRENCY": "3",
    "VERTEX_AI_IMAGE_MAX_CONCURRENCY": "1",
    "IMAGE_GROUPING_REVIEW_MAX_RETRIES": "3",
}

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _resolve_env_path() -> Path:
    candidates = [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT.parents[1] / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def apply_feishu_interactive_defaults() -> None:
    for key, value in FEISHU_INTERACTIVE_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def configure_windows_stdio() -> None:
    if sys.platform != "win32":
        return
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feishu-first 内容编排入口")
    parser.add_argument("--topic", required=True, help="主题")
    parser.add_argument("--audience", required=True, help="目标受众")
    parser.add_argument("--message", default="", help="补充说明或原始用户消息")
    parser.add_argument(
        "--route",
        choices=["image_post", "article_post", "video_post"],
        default=None,
        help="提供路线线索；不提供时由 orchestrator 根据对话上下文动态选择",
    )
    parser.add_argument(
        "--style",
        action="append",
        default=[],
        help="风格约束，可重复传入，如 --style 纯色背景 --style 单套展示",
    )
    parser.add_argument(
        "--explore",
        action="store_true",
        help="在原始消息中追加开放探索指令；路线仍由 orchestrator 根据上下文动态决定",
    )
    parser.add_argument(
        "--no-feishu",
        action="store_true",
        help="只生成交付包，不发送到飞书",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="快速验链路：临时降低研究/审核/分组/图片重试参数",
    )
    parser.add_argument("--chat-id", default=None, help="可选，覆盖默认飞书 chat_id")
    parser.add_argument("--run-id", default=None, help="可选，自定义 run_id")
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv
    load_dotenv(_resolve_env_path())
    apply_feishu_interactive_defaults()

    import logfire
    logfire.configure(
        send_to_logfire="if-token-present",
        environment="development",
        service_name="xiaohongshu-agent-feishu-orchestrator",
    )
    logfire.instrument_pydantic_ai()

    from src.orchestration import (
        ContentRoute,
        ConversationRequest,
        DeliveryPackageSender,
        FeishuContentOrchestrator,
    )
    from src.orchestration.smoke import orchestration_smoke_test_overrides
    from src.utils.feishu_notifier import get_feishu_notifier
    from src.utils.logger import get_logger, setup_logging

    setup_logging()
    logger = get_logger(__name__)

    sender = None
    if not args.no_feishu:
        sender = DeliveryPackageSender(notifier=get_feishu_notifier())

    orchestrator = FeishuContentOrchestrator(
        image_runner=None,
        article_runner=None,
        video_runner=None,
    )
    if sender is not None:
        orchestrator.image_runner.delivery_sender = sender
        orchestrator.article_runner.delivery_sender = sender
        orchestrator.video_runner.delivery_sender = sender

    message = args.message
    if args.explore:
        message = (message + "\n" if message else "") + "请自主探索并决定内容路线。"

    request = ConversationRequest(
        topic=args.topic,
        audience=args.audience,
        message=message,
        route_hint=ContentRoute(args.route) if args.route else None,
        style_constraints=list(args.style),
    )
    if args.smoke_test:
        logger.info("启用 feishu_orchestrator smoke-test 模式：降低研究/审核/分组/图片重试参数")

    with orchestration_smoke_test_overrides(args.smoke_test):
        result = await orchestrator.run_request(
            request,
            chat_id=args.chat_id,
            run_id=args.run_id,
            send_to_feishu=not args.no_feishu,
        )

    if result.payload is not None:
        logger.info("路线: %s", result.payload.route)
        logger.info("标题: %s", result.payload.title)
        logger.info("摘要: %s", result.payload.summary)
        logger.info("附件数: %d", len(result.payload.artifacts))
        return 0

    logger.error("执行失败: %s", result.error_message or result.summary)
    return 1


def main() -> None:
    configure_windows_stdio()
    raise SystemExit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()
