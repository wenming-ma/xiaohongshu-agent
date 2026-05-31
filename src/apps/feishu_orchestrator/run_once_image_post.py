from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.apps.feishu_orchestrator.serve import (  # noqa: E402
    _resolve_env_path,
    apply_feishu_interactive_defaults,
)


def configure_windows_stdio() -> None:
    if sys.platform != "win32":
        return
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one image-post workflow and optionally send it to Feishu.")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--message", default="")
    parser.add_argument("--image-count", type=int, default=None)
    parser.add_argument("--style", action="append", default=[])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--chat-id", default=None)
    parser.add_argument("--send-to-feishu", action="store_true")
    parser.add_argument("--research-envelope", default=None)
    parser.add_argument("--research-min-posts", type=int, default=None)
    parser.add_argument("--research-validation-retries", type=int, default=None)
    parser.add_argument("--research-min-key-infos", type=int, default=None)
    parser.add_argument("--research-min-cases", type=int, default=None)
    parser.add_argument("--image-max-retries", type=int, default=None)
    parser.add_argument("--image-size", default=None)
    parser.add_argument("--image-aspect-ratio", default=None)
    return parser.parse_args()


async def main_async() -> int:
    from dotenv import load_dotenv

    load_dotenv(_resolve_env_path())
    apply_feishu_interactive_defaults()

    import logfire

    logfire.configure(
        send_to_logfire="if-token-present",
        environment="development",
        service_name="xiaohongshu-agent-feishu-run-once",
    )
    logfire.instrument_pydantic_ai()

    from src.orchestration import (
        ContentRoute,
        ConversationRequest,
        DeliveryPackageSender,
        ImagePostOrchestrator,
        ResultEnvelope,
    )
    from src.orchestration.run_options import ImagePostRunOptions
    from src.agents.image_post.schemas import ResearchResult
    from src.utils.feishu_notifier import get_feishu_notifier
    from src.utils.logger import get_logger, setup_logging

    setup_logging()
    logger = get_logger(__name__)
    args = parse_args()
    run_options = ImagePostRunOptions()
    if args.research_min_posts is not None:
        run_options.research.min_posts_researched = args.research_min_posts
    if args.research_validation_retries is not None:
        run_options.research.validation_max_retries = args.research_validation_retries
    if args.research_min_key_infos is not None:
        run_options.research.min_key_infos = args.research_min_key_infos
    if args.research_min_cases is not None:
        run_options.research.min_cases = args.research_min_cases
    if args.image_max_retries is not None:
        run_options.image.max_retries = args.image_max_retries
    if args.image_size is not None:
        run_options.image.image_size = args.image_size
    if args.image_aspect_ratio is not None:
        run_options.image.aspect_ratio = args.image_aspect_ratio

    research_agent_factory = None
    if args.research_envelope:
        research_path = Path(args.research_envelope)
        research_envelope = ResultEnvelope[ResearchResult].model_validate_json(
            research_path.read_text(encoding="utf-8")
        )
        if research_envelope.payload is None:
            raise ValueError(f"research envelope has no payload: {research_path}")
        research_payload = research_envelope.payload

        class LoadedResearchAgent:
            async def forward(
                self,
                topic: str,
                target_audience: str,
                output_dir: Path | None = None,
            ) -> ResearchResult:
                logger.info("使用已有 research envelope，跳过浏览器研究阶段: %s", research_path)
                return research_payload

        research_agent_factory = LoadedResearchAgent

    sender = DeliveryPackageSender(notifier=get_feishu_notifier()) if args.send_to_feishu else None
    orchestrator_kwargs = {"delivery_sender": sender}
    if research_agent_factory is not None:
        orchestrator_kwargs["research_agent_factory"] = research_agent_factory
    orchestrator = ImagePostOrchestrator(run_options=run_options, **orchestrator_kwargs)
    request = ConversationRequest(
        topic=args.topic,
        audience=args.audience,
        message=args.message,
        route_hint=ContentRoute.IMAGE_POST,
        style_constraints=list(args.style),
        image_count=args.image_count,
    )

    logger.info("启动一次性 image_post 工作流: topic=%s image_count=%s", args.topic, args.image_count)
    result = await orchestrator.run(
        request,
        run_id=args.run_id,
        chat_id=args.chat_id,
        send_to_feishu=args.send_to_feishu,
    )
    logger.info("一次性 image_post 工作流结束: status=%s summary=%s", result.status, result.summary)
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "success" else 1


def main() -> None:
    configure_windows_stdio()
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
