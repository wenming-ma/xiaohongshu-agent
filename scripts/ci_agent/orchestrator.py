from __future__ import annotations
import asyncio
import logging
import re
import subprocess
import time
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from .config import ClusterConfig
from .state import AttemptRecord, ClusterState

logger = logging.getLogger(__name__)

TAIL_CHARS = 4000
ALL_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

FIXER_PROMPT = """\
You are an autonomous CI agent for a Xiaohongshu video post pipeline.
The pipeline phases: research -> download -> dub -> content -> cover -> publish.
Tech stack: pydantic-ai, Playwright MCP, yt-dlp, Whisper, FFmpeg, TTS providers, uv.

A script run has failed. Your job:
1. Analyze the error output and read relevant source files to understand the root cause
2. Fix the issue - modify code, config, or dependencies as needed
3. Use git to commit your changes (stage specific files, write a descriptive message)

Rules:
- Make the SMALLEST change that fixes the issue
- Do NOT refactor or improve unrelated code
- After editing, read the file back to verify
- For dependency issues, use uv (uv add, uv sync), not pip
- For git: never use "git add ." - stage specific files only
- Commit message format: "fix(<scope>): <description>"

You have full tool access: Read, Write, Edit, Bash, Glob, Grep.
Use Bash for git commands, uv commands, and any other shell operations.\
"""

VALIDATOR_PROMPT = """\
You are a senior engineer evaluating whether a code fix was effective.

You will receive stderr output from before and after a fix attempt.
You may also read source files to better understand the situation.

Output in this EXACT format:

VERDICT: <SAME_ERROR|PROGRESS>
REASON: <one paragraph explanation>

Guidelines:
- SAME_ERROR: The root cause is identical, the fix had no real effect. Should rollback.
- PROGRESS: The error changed, disappeared, or moved to a different phase. Keep the fix.\
"""


async def _run_agent(prompt: str, config: ClusterConfig, system_prompt: str, tools: list[str] | None = None) -> str:
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=tools or ALL_TOOLS,
        permission_mode="bypassPermissions",
        max_turns=config.max_worker_turns,
        model=config.model,
        cwd=str(config.project_root),
    )
    result_text = ""
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        result_text = block.text
            elif isinstance(msg, ResultMessage):
                if msg.result:
                    result_text = msg.result
                if msg.is_error:
                    logger.warning("Agent error: %s", msg.errors)
    except Exception as e:
        logger.error("Agent failed: %s", e)
        result_text = f"Agent error: {e}"
    return result_text


class Orchestrator:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self.state = ClusterState(target_command=config.target_command)

    async def run(self) -> bool:
        self._init_git_state()
        if self.config.git_branch:
            self._create_branch(self.config.git_branch)

        consecutive_rollbacks = 0

        for attempt_num in range(1, self.config.max_attempts + 1):
            logger.info("=" * 60)
            logger.info("ATTEMPT #%d / %d", attempt_num, self.config.max_attempts)
            logger.info("=" * 60)

            record = AttemptRecord(attempt_number=attempt_num)

            # Step 1: Run target script
            exit_code, stdout, stderr = self._run_target()
            record.exit_code = exit_code
            record.stdout_tail = stdout[-TAIL_CHARS:]
            record.stderr_tail = stderr[-TAIL_CHARS:]

            if exit_code == 0:
                logger.info("SUCCESS on attempt #%d", attempt_num)
                self.state.status = "success"
                self.state.attempts.append(record)
                self.state.save(self.config.state_file)
                return True

            logger.warning("Script failed with exit code %d", exit_code)

            # Step 2: Agent analyzes, fixes, and commits
            history = self.state.format_attempt_history()
            fixer_prompt = (
                f"The script failed with exit code {exit_code}.\n\n"
                f"=== STDOUT (tail) ===\n{stdout[-TAIL_CHARS:]}\n\n"
                f"=== STDERR (tail) ===\n{stderr[-TAIL_CHARS:]}\n\n"
                f"=== Previous attempts (DO NOT repeat failed fixes) ===\n{history}\n\n"
                "Analyze the error, fix it, and commit your changes."
            )
            logger.info("Running Fixer agent...")
            fix_result = await _run_agent(fixer_prompt, self.config, FIXER_PROMPT)
            record.fix_description = fix_result

            # Step 3: Validate - run script again
            logger.info("Running validation...")
            exit_code_2, stdout_2, stderr_2 = self._run_target()

            if exit_code_2 == 0:
                logger.info("SUCCESS after fix on attempt #%d", attempt_num)
                self.state.status = "success"
                self.state.attempts.append(record)
                self.state.save(self.config.state_file)
                return True

            # Step 4: Agent judges whether fix helped
            validator_prompt = (
                f"=== STDERR BEFORE FIX ===\n{stderr[-TAIL_CHARS:]}\n\n"
                f"=== STDERR AFTER FIX ===\n{stderr_2[-TAIL_CHARS:]}\n\n"
                f"=== FIX APPLIED ===\n{fix_result[:1000]}\n\n"
                "Judge whether the fix was effective."
            )
            logger.info("Running Validator agent...")
            verdict_text = await _run_agent(
                validator_prompt, self.config, VALIDATOR_PROMPT, ["Read", "Grep"],
            )
            verdict = self._parse_verdict(verdict_text)
            logger.info("Verdict: %s", verdict)

            if verdict == "SAME_ERROR":
                logger.warning("Agent says SAME_ERROR -- rolling back")
                self._rollback_last_commit()
                record.rolled_back = True
                consecutive_rollbacks += 1
                if consecutive_rollbacks >= self.config.max_consecutive_rollbacks:
                    logger.error("Max consecutive rollbacks (%d) -- stopping", self.config.max_consecutive_rollbacks)
                    self.state.status = "stuck"
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    return False
            else:
                logger.info("Agent says PROGRESS -- keeping fix")
                consecutive_rollbacks = 0

            self.state.attempts.append(record)
            self.state.save(self.config.state_file)

            if self.config.sleep_between_attempts > 0:
                time.sleep(self.config.sleep_between_attempts)

        logger.error("Max attempts (%d) exhausted", self.config.max_attempts)
        self.state.status = "exhausted"
        self.state.save(self.config.state_file)
        return False

    # --- Minimal helpers (only things an agent can't do) ---

    def _run_target(self) -> tuple[int, str, str]:
        logger.info("Running: %s", self.config.target_command)
        try:
            result = subprocess.run(
                self.config.target_command,
                shell=True,
                cwd=str(self.config.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.target_timeout,
                env=self.config.build_env(),
            )
            return result.returncode, result.stdout or "", result.stderr or ""
        except subprocess.TimeoutExpired:
            return -1, "", f"TIMEOUT after {self.config.target_timeout}s"
        except Exception as e:
            return -1, "", str(e)

    def _init_git_state(self) -> None:
        r = subprocess.run(["git", "branch", "--show-current"],
                           cwd=str(self.config.project_root), capture_output=True, text=True)
        self.state.original_branch = r.stdout.strip()
        self.state.current_branch = r.stdout.strip()

    def _create_branch(self, name: str) -> None:
        subprocess.run(["git", "checkout", "-b", name],
                       cwd=str(self.config.project_root), capture_output=True, text=True)
        self.state.current_branch = name

    def _parse_verdict(self, text: str) -> str:
        m = re.search(r"VERDICT:\s*(SAME_ERROR|PROGRESS)", text)
        return m.group(1) if m else "PROGRESS"

    def _rollback_last_commit(self) -> None:
        r = subprocess.run(["git", "log", "--oneline", "-5"],
                           cwd=str(self.config.project_root), capture_output=True, text=True)
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            prev = lines[1].split()[0]
            subprocess.run(["git", "reset", "--hard", prev],
                           cwd=str(self.config.project_root), capture_output=True, text=True)
            logger.info("Rolled back to %s", prev)
