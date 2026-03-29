#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk"]
# ///
"""
Autonomous video post agent: runs the XHS video pipeline, auto-fixes errors,
and retries until all topics are published.

Usage:
    uv run python scripts/run_video_post_agent.py
    uv run python scripts/run_video_post_agent.py --start-index 5
    uv run python scripts/run_video_post_agent.py --start-index 5 --limit 3
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)


def log(msg: str) -> None:
    """Print a timestamped log line."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSHOP_DIR = PROJECT_ROOT / "workshop" / "video_post"
RUN_PS1 = WORKSHOP_DIR / "run.ps1"


# ---------------------------------------------------------------------------
# MCP Tool: run_video_post
# ---------------------------------------------------------------------------

RUN_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start_index": {
            "type": "integer",
            "description": "1-based index of the first topic to process. Default: 1",
        },
        "limit": {
            "type": "integer",
            "description": (
                "Maximum number of topics to process. 0 means all remaining. Default: 0"
            ),
        },
    },
    "required": [],
}


@tool(
    "run_video_post",
    "Run the XHS video post pipeline (run.ps1). Returns stdout/stderr and exit code.",
    RUN_TOOL_SCHEMA,
)
async def run_video_post(args: dict[str, Any]) -> dict[str, Any]:
    start_index = args.get("start_index", 1)
    limit = args.get("limit", 0)

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUN_PS1),
        "-StartIndex",
        str(start_index),
    ]
    if limit > 0:
        cmd.extend(["-Limit", str(limit)])

    limit_desc = f", limit={limit}" if limit > 0 else ""
    log(f">>> run_video_post(start_index={start_index}{limit_desc})")
    log(f"    cmd: {' '.join(cmd)}")
    t0 = time.monotonic()

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        stdout_bytes, _ = await process.communicate()
        output = stdout_bytes.decode("utf-8", errors="replace")
        exit_code = process.returncode or 0
        elapsed = time.monotonic() - t0
        log(f"<<< run_video_post finished in {elapsed:.1f}s, exit_code={exit_code}")
    except FileNotFoundError:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: PowerShell not found. Ensure powershell is on PATH.",
                }
            ],
            "is_error": True,
        }
    except Exception as exc:
        return {
            "content": [{"type": "text", "text": f"Error launching run.ps1: {exc}"}],
            "is_error": True,
        }

    status_label = {0: "SUCCESS", 1: "PARTIAL_FAILURE", 2: "CRASH"}.get(
        exit_code, f"UNKNOWN({exit_code})"
    )

    # Truncate extremely long output to stay within context limits
    MAX_OUTPUT = 80_000
    if len(output) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        output = (
            output[:half]
            + "\n\n... [output truncated] ...\n\n"
            + output[-half:]
        )

    text = f"Exit code: {exit_code} ({status_label})\n\n{output}"
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def build_system_prompt(start_index: int, limit: int) -> str:
    limit_desc = f"up to {limit} topics" if limit > 0 else "all remaining topics"
    return f"""\
You are an autonomous CI agent for the xiaohongshu-agent project. Your job is to
run the video post pipeline and fix any errors that prevent it from completing
successfully.

## Your Workflow

1. Call the `run_video_post` tool with start_index={start_index} and \
limit={limit if limit > 0 else 0} to run the pipeline for ONE topic at a time.
2. Read the ENTIRE output carefully — not just the exit code. Check for:
   - Exit code 0: The topic finished, but there may still be issues (see step 3).
   - Exit code 1: Some topics failed. Read the failure details.
   - Exit code 2: The batch crashed. Read the crash error.
3. **Even when exit code is 0**, review the full process log for:
   - Warnings, errors, or exceptions that were caught and skipped
   - Steps that silently fell back to defaults or were skipped entirely
   - Missing or empty outputs in intermediate steps (e.g., empty subtitles,
     missing audio segments, skipped TTS lines, failed downloads)
   - Any "retry", "fallback", "skip", "failed" keywords in the logs
   If you find such issues, investigate the root cause, fix the code, and
   re-run the same topic to verify the fix.
4. Only after a truly clean run (exit code 0 AND no concerning warnings/errors
   in the process log), move to the next topic by incrementing start_index.
5. If the failure log files are mentioned in the output (e.g.,
   video_post_failures_*.jsonl, video_post_crash_*.json), read them for
   additional error context.

## Important Guidelines

- The project root is the current working directory.
- The pipeline code is under `src/agents/video_post/`.
- The batch runner is `workshop/video_post/run.py`.
- Failure logs are written to `workshop/video_post/`.
- When fixing code, make minimal, targeted changes. Do not refactor unrelated code.
- If an error seems to be a transient issue (network timeout, API rate limit),
  just re-run the tool without code changes.
- If you encounter the same error repeatedly after fixing, try a different
  approach or read more context from the codebase.
- Do NOT modify `workshop/video_post/topics.json`.
- Process ONE topic at a time (limit=1). After a clean run, increment
  start_index and process the next topic. Continue until all topics are done.
- A "clean run" means exit code 0 AND no skipped errors or concerning warnings.
- After all topics are processed, summarize what you did and end.
- If after extensive attempts you cannot fix an issue, explain what you tried
  and what the remaining problem is, then stop.

## Project Context

This project downloads videos from YouTube/TikTok, transcribes them, translates
subtitles to Chinese, generates Chinese voiceover (TTS), edits the video with
Chinese audio/subtitles, and publishes to Xiaohongshu (Chinese social media).
The pipeline involves: research agent, video download, ASR (Whisper), subtitle
translation, TTS dubbing (s2.cpp), video editing, and XHS publishing.

You are processing {limit_desc} starting from index {start_index}.
"""


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------


async def run_agent(start_index: int, limit: int) -> None:
    log("Initializing agent...")
    server = create_sdk_mcp_server(name="video", tools=[run_video_post])

    options = ClaudeAgentOptions(
        system_prompt=build_system_prompt(start_index, limit),
        permission_mode="bypassPermissions",
        # All default Claude Code tools (Read, Write, Edit, Bash, Grep, Glob, etc.)
        tools={"type": "preset", "preset": "claude_code"},
        mcp_servers={"video": server},
        allowed_tools=["mcp__video__run_video_post"],
        cwd=str(PROJECT_ROOT),
        # Load user settings (inherits ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, etc.)
        setting_sources=["user"],
    )

    prompt = f"Run the video post pipeline starting from topic index {start_index}"
    if limit > 0:
        prompt += f", processing up to {limit} topics"
    prompt += ". Begin now."

    log(f"Sending prompt to Claude: {prompt}")
    log("Waiting for Claude Code CLI to start...")
    turn = 0

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                tools = message.data.get("tools", [])
                mcp = message.data.get("mcp_servers", {})
                log(f"Claude Code session initialized ({len(tools)} tools, mcp={list(mcp.keys()) if isinstance(mcp, dict) else mcp})")
        elif isinstance(message, AssistantMessage):
            turn += 1
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text, flush=True)
                elif isinstance(block, ToolUseBlock):
                    log(f"[Turn {turn}] Tool call: {block.name}({block.input})")
        elif isinstance(message, ResultMessage):
            print(f"\n{'=' * 60}", flush=True)
            cost = (
                f"Cost: ${message.total_cost_usd:.4f}"
                if message.total_cost_usd
                else ""
            )
            log(
                f"Session complete. {cost} "
                f"Turns: {message.num_turns}, "
                f"Duration: {message.duration_ms / 1000:.1f}s"
            )
            if message.is_error:
                log(f"Ended with error: {message.result}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous XHS video post agent — auto-runs, auto-fixes, auto-retries."
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based topic index to start from (default: 1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max topics to process, 0 = all (default: 0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log(f"Video Post Agent starting (start_index={args.start_index}, limit={args.limit})")
    log(f"Project root: {PROJECT_ROOT}")
    log(f"run.ps1 path: {RUN_PS1} (exists={RUN_PS1.exists()})")
    try:
        asyncio.run(run_agent(args.start_index, args.limit))
    except KeyboardInterrupt:
        log("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        log(f"Agent failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
