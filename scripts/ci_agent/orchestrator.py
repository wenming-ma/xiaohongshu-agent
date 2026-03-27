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
    AgentDefinition,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from .config import ClusterConfig
from .state import AttemptRecord, ClusterState

logger = logging.getLogger(__name__)

TAIL_CHARS = 3000

ERROR_ANALYZER_PROMPT = """\
You are an expert Python debugger analyzing errors from a Xiaohongshu video post pipeline.

The pipeline phases: research -> download -> dub -> content -> cover -> publish.
Tech stack: pydantic-ai, Playwright MCP, yt-dlp, Whisper, FFmpeg, various TTS providers.

Your task:
1. Read the error output carefully
2. Use tools to read relevant source files and trace the root cause
3. Classify the error and output in this EXACT format:

CATEGORY: <CODE_ERROR|DEPENDENCY_ERROR|CONFIG_ERROR|RUNTIME_ERROR|UNKNOWN>
FILE: <file path>
LINE: <line number or "unknown">
ROOT_CAUSE: <one paragraph>
FIX_PLAN: <concrete steps>

Do NOT suggest fixes that have already been tried and rolled back.\
"""

CODE_FIXER_PROMPT = """\
You are an expert Python developer fixing bugs in a Xiaohongshu video post pipeline.
Tech stack: pydantic-ai, Playwright MCP, yt-dlp, FFmpeg, TTS providers, uv package manager.

Rules:
- Make the SMALLEST change that fixes the issue
- Do NOT refactor or improve unrelated code
- Verify your fix by reading the file back after editing
- Do NOT repeat fixes from the attempt history that were already tried and rolled back\
"""

DEPENDENCY_FIXER_PROMPT = """\
You are an expert Python developer fixing dependency issues.
The project uses uv for package management with pyproject.toml.

Rules:
- Use uv commands (uv add, uv sync, uv pip install) not pip directly
- After pyproject.toml changes, run "uv sync"
- Verify the fix with "uv pip show <package>"
- Do NOT repeat fixes from the attempt history\
"""

GIT_MANAGER_PROMPT = """\
You are a git operations specialist.

For COMMIT: stage only the specified files, use message format "fix(<scope>): <description>"
For ROLLBACK: verify the commit exists, then reset --hard to the target.

Never use "git add ." or "git add -A".\
"""


def _build_worker_options(config: ClusterConfig, system_prompt: str, tools: list[str]) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=tools,
        permission_mode="bypassPermissions",
        max_turns=config.max_worker_turns,
        model=config.model,
        cwd=str(config.project_root),
    )


async def _run_worker(prompt: str, options: ClaudeAgentOptions) -> str:
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
                    logger.warning("Worker returned error: %s", msg.errors)
    except Exception as e:
        logger.error("Worker failed: %s", e)
        result_text = f"Worker error: {e}"
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

            # Step 2: Success?
            if exit_code == 0:
                logger.info("SUCCESS on attempt #%d", attempt_num)
                self.state.status = "success"
                self.state.attempts.append(record)
                self.state.save(self.config.state_file)
                return True

            logger.warning("Script failed with exit code %d", exit_code)

            # Step 3: Collect logs
            log_content = self._collect_logs()
            history = self.state.format_attempt_history()

            # Step 4: Error Analysis
            analysis_prompt = (
                f"The video post pipeline script exited with code {exit_code}.\n\n"
                f"=== STDOUT (last {TAIL_CHARS} chars) ===\n{stdout[-TAIL_CHARS:]}\n\n"
                f"=== STDERR (last {TAIL_CHARS} chars) ===\n{stderr[-TAIL_CHARS:]}\n\n"
                f"=== Log Files ===\n{log_content}\n\n"
                f"=== Previous Attempts (DO NOT repeat) ===\n{history}\n\n"
                "Diagnose the root cause following your output format."
            )
            analysis_options = _build_worker_options(
                self.config, ERROR_ANALYZER_PROMPT,
                ["Read", "Glob", "Grep", "Bash"],
            )
            logger.info("Running ErrorAnalyzer...")
            diagnosis = await _run_worker(analysis_prompt, analysis_options)
            record.diagnosis = diagnosis

            # Step 5: Parse category
            category = self._parse_category(diagnosis)
            record.diagnosis_category = category
            logger.info("Diagnosis category: %s", category)

            if category == "RUNTIME_ERROR":
                logger.info("Runtime error -- sleeping before retry")
                time.sleep(self.config.sleep_between_attempts * 6)
                self.state.attempts.append(record)
                self.state.save(self.config.state_file)
                continue

            # Step 6: Apply fix
            fix_prompt = (
                f"Diagnosis:\n{diagnosis}\n\n"
                "Apply the fix described above. After making changes, read the modified "
                "file(s) back to verify correctness.\n\n"
                f"Previous failed fixes (DO NOT repeat):\n{history}"
            )
            if category == "DEPENDENCY_ERROR":
                fix_options = _build_worker_options(
                    self.config, DEPENDENCY_FIXER_PROMPT,
                    ["Read", "Bash", "Edit", "Write", "Glob", "Grep"],
                )
            else:
                fix_options = _build_worker_options(
                    self.config, CODE_FIXER_PROMPT,
                    ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                )
            logger.info("Running %s...", "DependencyFixer" if category == "DEPENDENCY_ERROR" else "CodeFixer")
            fix_result = await _run_worker(fix_prompt, fix_options)
            record.fix_description = fix_result

            # Step 7: Check what changed and commit
            diff_output = self._git_diff()
            if diff_output.strip():
                modified = self._get_modified_files()
                record.files_modified = modified
                commit_msg = self._build_commit_message(category, fix_result)
                commit_prompt = (
                    f"Commit these modified files with message: {commit_msg}\n"
                    f"Files: {modified}"
                )
                git_options = _build_worker_options(
                    self.config, GIT_MANAGER_PROMPT,
                    ["Bash"],
                )
                logger.info("Running GitManager to commit...")
                git_result = await _run_worker(commit_prompt, git_options)
                record.committed = True
                record.commit_hash = self._extract_commit_hash(git_result)
            else:
                logger.warning("No file changes detected after fix")

            # Step 8: Quick validation
            logger.info("Running validation...")
            exit_code_2, stdout_2, stderr_2 = self._run_target()

            if exit_code_2 == 0:
                logger.info("SUCCESS after fix on attempt #%d", attempt_num)
                self.state.status = "success"
                self.state.attempts.append(record)
                self.state.save(self.config.state_file)
                return True

            # Step 9: Same error? Rollback
            if self._is_same_error(record.stderr_tail, stderr_2[-TAIL_CHARS:]):
                logger.warning("Same error after fix -- rolling back")
                if record.committed and record.commit_hash:
                    self._rollback_last_commit()
                    record.rolled_back = True
                    consecutive_rollbacks += 1
                if consecutive_rollbacks >= self.config.max_consecutive_rollbacks:
                    logger.error("Max consecutive rollbacks reached -- stopping")
                    self.state.status = "stuck"
                    self.state.attempts.append(record)
                    self.state.save(self.config.state_file)
                    return False
            else:
                logger.info("Different error -- progress made, continuing")
                consecutive_rollbacks = 0

            self.state.attempts.append(record)
            self.state.save(self.config.state_file)

            if self.config.sleep_between_attempts > 0:
                time.sleep(self.config.sleep_between_attempts)

        logger.error("Max attempts (%d) exhausted", self.config.max_attempts)
        self.state.status = "exhausted"
        self.state.save(self.config.state_file)
        return False

    # --- Helpers ---

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

    def _collect_logs(self) -> str:
        workshop = self.config.project_root / "workshop" / "video_post"
        patterns = ["video_post_crash_*.json", "video_post_failed_*.json",
                     "video_post_failures_*.jsonl", "video_post_summary_*.json"]
        parts = []
        for pat in patterns:
            for p in sorted(workshop.glob(pat), key=lambda x: x.stat().st_mtime, reverse=True)[:1]:
                try:
                    parts.append(f"=== {p.name} ===\n{p.read_text(encoding='utf-8', errors='replace')[:3000]}")
                except Exception:
                    pass
        return "\n\n".join(parts) if parts else "(no log files found)"

    def _parse_category(self, text: str) -> str:
        m = re.search(r"CATEGORY:\s*(CODE_ERROR|DEPENDENCY_ERROR|CONFIG_ERROR|RUNTIME_ERROR|UNKNOWN)", text)
        return m.group(1) if m else "UNKNOWN"

    def _git_diff(self) -> str:
        r = subprocess.run(["git", "diff", "--stat"], cwd=str(self.config.project_root),
                           capture_output=True, text=True)
        return r.stdout

    def _get_modified_files(self) -> list[str]:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=str(self.config.project_root),
                           capture_output=True, text=True)
        files = []
        for line in r.stdout.splitlines():
            if line.strip():
                files.append(line[3:].strip())
        return files

    def _build_commit_message(self, category: str, fix_desc: str) -> str:
        scope = {"CODE_ERROR": "code", "DEPENDENCY_ERROR": "deps", "CONFIG_ERROR": "config"}.get(category, "fix")
        summary = fix_desc[:100].replace("\n", " ").strip()
        return f"fix({scope}): {summary}"

    def _extract_commit_hash(self, text: str) -> str:
        m = re.search(r"[a-f0-9]{7,40}", text)
        return m.group(0) if m else ""

    def _is_same_error(self, old: str, new: str) -> bool:
        if not old or not new:
            return False
        old_lines = set(l.strip() for l in old.splitlines() if re.search(r"Error:|Exception:|Traceback", l))
        new_lines = set(l.strip() for l in new.splitlines() if re.search(r"Error:|Exception:|Traceback", l))
        if not old_lines or not new_lines:
            return old[-500:] == new[-500:]
        return len(old_lines & new_lines) / max(len(old_lines), 1) > 0.5

    def _rollback_last_commit(self) -> None:
        r = subprocess.run(["git", "log", "--oneline", "-5"],
                           cwd=str(self.config.project_root), capture_output=True, text=True)
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            prev = lines[1].split()[0]
            subprocess.run(["git", "reset", "--hard", prev],
                           cwd=str(self.config.project_root), capture_output=True, text=True)
            logger.info("Rolled back to %s", prev)
