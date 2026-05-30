"""
CI Agent - Autonomous pipeline runner and fixer

Runs the pipeline inside an isolated git worktree and uses Deep Agents
to diagnose, fix, validate, and retry until the video post pipeline succeeds.

Usage:
    uv run python scripts/ci_agent/main.py
    uv run python scripts/ci_agent/main.py --max-attempts 30
    uv run python scripts/ci_agent/main.py --model openai:gpt-5.5
    uv run python scripts/ci_agent/main.py --worker-model MiniMax-M2.7
    uv run python scripts/ci_agent/main.py --resume .cache/ci_agent/sessions/<session_id>/state.json
    uv run python scripts/ci_agent/main.py --no-publish
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
    parser.add_argument("--model", default="openai:gpt-5.5")
    parser.add_argument("--worker-model", default=None, help="Override the non-controller worker model")
    parser.add_argument("--resume", type=Path, default=None, help="Resume from state.json")
    parser.add_argument("--branch", default=None, help="Isolated git branch for fixes")
    parser.add_argument("--publish", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-publish", action="store_true", help="Disable publishing for the target command")
    parser.add_argument("--limit", type=int, default=1, help="Topics limit")
    parser.add_argument("--timeout", type=int, default=1800, help="Script timeout (seconds)")
    parser.add_argument("--sleep", type=int, default=5, help="Sleep between attempts")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def main() -> None:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    setup_logging(args.verbose)
    resume_state = ClusterState.load(args.resume) if args.resume else None

    overrides: dict = {
        "max_attempts": args.max_attempts,
        "model": args.model,
        "target_timeout": args.timeout,
        "sleep_between_attempts": args.sleep,
    }
    if args.worker_model:
        overrides["worker_model"] = args.worker_model
    if resume_state:
        overrides["session_id"] = resume_state.session_id
        overrides["state_file"] = args.resume
        if resume_state.worktree_root:
            overrides["worktree_root"] = Path(resume_state.worktree_root)
        if args.branch:
            overrides["git_branch"] = args.branch
        elif resume_state.current_branch:
            overrides["git_branch"] = resume_state.current_branch
    elif args.branch:
        overrides["git_branch"] = args.branch

    if args.target:
        overrides["target_command"] = args.target
    else:
        parts = [
            "uv run python workshop/video_post/run.py",
            "--topics-file workshop/video_post/topics.json",
            f"--limit {args.limit}",
        ]
        if args.no_publish:
            parts.append("--no-publish")
        overrides["target_command"] = " ".join(parts)

    config = ClusterConfig.from_env(**overrides)

    logger.info("=" * 60)
    logger.info("CI Agent Starting (Deep Agents)")
    logger.info("Controller model: %s", config.model)
    logger.info("Worker model: %s", config.worker_model)
    logger.info("Target: %s", config.target_command)
    logger.info("Max attempts: %d", config.max_attempts)
    logger.info("Minimum attempts before finish: %d", config.min_attempts_before_finish)
    logger.info("Timeout: %ds", config.target_timeout)
    logger.info("Branch: %s", config.git_branch)
    logger.info("Worktree: %s", config.worktree_root)
    logger.info("State file: %s", config.state_file)
    logger.info("=" * 60)

    orchestrator = Orchestrator(config)

    if resume_state:
        logger.info("Resuming from %s", args.resume)
        orchestrator.state = resume_state
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
