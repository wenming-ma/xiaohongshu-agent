from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

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
    """Use practical defaults for always-on chat workflows unless .env overrides them."""
    for key, value in FEISHU_INTERACTIVE_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def configure_windows_stdio() -> None:
    if sys.platform != "win32":
        return
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


async def main_async() -> int:
    from dotenv import load_dotenv

    load_dotenv(_resolve_env_path())
    apply_feishu_interactive_defaults()

    import logfire

    logfire.configure(
        send_to_logfire="if-token-present",
        environment="development",
        service_name="xiaohongshu-agent-feishu-listener",
    )
    logfire.instrument_pydantic_ai()

    from src.orchestration import DeliveryPackageSender, FeishuContentOrchestrator, FeishuWorkflowService
    from src.orchestration.smoke import orchestration_smoke_test_overrides
    from src.utils.feishu_notifier import get_feishu_notifier
    from src.utils.logger import get_logger, setup_logging

    setup_logging()
    logger = get_logger(__name__)

    notifier = get_feishu_notifier()
    sender = DeliveryPackageSender(notifier=notifier)
    orchestrator = FeishuContentOrchestrator()
    orchestrator.image_runner.delivery_sender = sender
    orchestrator.article_runner.delivery_sender = sender
    orchestrator.video_runner.delivery_sender = sender

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
    )
    smoke_test = os.getenv("FEISHU_ORCHESTRATOR_SMOKE_TEST", "").lower() in {"1", "true", "yes", "on"}
    if smoke_test:
        logger.info("启用 Feishu 常驻工作流 smoke-test 模式")
    logger.info("启动 Feishu 常驻工作流监听服务")
    with orchestration_smoke_test_overrides(smoke_test):
        await service.serve_forever()
    return 0


def main() -> None:
    configure_windows_stdio()
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
