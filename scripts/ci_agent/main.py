"""
CI Agent - Autonomous pipeline runner and fixer

Uses Claude Agent SDK to run, diagnose, fix, commit, and retry
until the video post pipeline succeeds.

Usage:
    uv run python scripts/ci_agent/main.py
    uv run python scripts/ci_agent/main.py --max-attempts 30
    uv run python scripts/ci_agent/main.py --model claude-sonnet-4-6
    uv run python scripts/ci_agent/main.py --resume scripts/ci_agent/state.json
    uv run python scripts/ci_agent/main.py --publish
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

from scripts.ci_agent.config import ClusterConfig, PROJECT_ROOT
from scripts.ci_agent.orchestrator import Orchestrator
from scripts.ci_agent.state import ClusterState

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous agent cluster: run > diagnose > fix > commit > retry"
    )
    parser.add_argument("--target", default=None, help="Override target command")
    parser.add_argument("--max-attempts", type=int, default=20)
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--resume", type=Path, default=None, help="Resume from state.json")
    parser.add_argument("--branch", default=None, help="Isolated git branch for fixes")
    parser.add_argument("--publish", action="store_true", help="Enable publishing")
    parser.add_argument("--limit", type=int, default=1, help="Topics limit")
    parser.add_argument("--timeout", type=int, default=600, help="Script timeout (seconds)")
    parser.add_argument("--sleep", type=int, default=5, help="Sleep between attempts")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def main() -> None:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    setup_logging(args.verbose)

    overrides: dict = {
        "max_attempts": args.max_attempts,
        "model": args.model,
        "target_timeout": args.timeout,
        "sleep_between_attempts": args.sleep,
        "git_branch": args.branch,
    }

    if args.target:
        overrides["target_command"] = args.target
    else:
        parts = [
            "uv run python workshop/video_post/run.py",
            "--topics-file workshop/video_post/topics.json",
            f"--limit {args.limit}",
        ]
        if not args.publish:
            parts.extend(["--no-publish", "--no-feishu"])
        overrides["target_command"] = " ".join(parts)

    config = ClusterConfig.from_env(**overrides)

    logger.info("=" * 60)
    logger.info("CI Agent Starting (Claude Agent SDK)")
    logger.info("Model: %s", config.model)
    logger.info("Target: %s", config.target_command)
    logger.info("Max attempts: %d", config.max_attempts)
    logger.info("Timeout: %ds", config.target_timeout)
    logger.info("Branch: %s", config.git_branch or "(current)")
    logger.info("=" * 60)

    orchestrator = Orchestrator(config)

    if args.resume:
        logger.info("Resuming from %s", args.resume)
        orchestrator.state = ClusterState.load(args.resume)
        orchestrator.state.status = "running"

    success = asyncio.run(orchestrator.run())

    if success:
        logger.info("Pipeline completed successfully!")
    else:
        logger.error("Failed after %d attempts. Status: %s",
                      len(orchestrator.state.attempts), orchestrator.state.status)
        logger.error("State saved to %s", config.state_file)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
