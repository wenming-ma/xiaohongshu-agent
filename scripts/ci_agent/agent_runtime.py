from __future__ import annotations

import html
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from deepagents import CompiledSubAgent, create_deep_agent
from deepagents.backends import FilesystemBackend, LocalShellBackend
from deepagents.backends.protocol import EditResult, WriteResult
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel, Field

from .config import ClusterConfig
from .state import ToolCallRecord, WorkerInvocation

logger = logging.getLogger(__name__)
TAIL_CHARS = 4000
WEB_SNIPPET_CHARS = 12000
CONTROLLER_MEMORY_SUMMARY_CHARS = 360
CONTROLLER_MEMORY_SHORT_CHARS = 160
CONTROLLER_MEMORY_MEDIUM_CHARS = 220


class ValidationToolResult(BaseModel):
    label: str
    exit_code: int
    duration_seconds: float
    started_at: str
    ended_at: str
    stdout: str = ""
    stderr: str = ""
    stdout_log_path: str = ""
    stderr_log_path: str = ""

    def to_summary(self) -> "ValidationRunReport":
        return ValidationRunReport(
            label=self.label,
            exit_code=self.exit_code,
            duration_seconds=self.duration_seconds,
            started_at=self.started_at,
            ended_at=self.ended_at,
            stdout_excerpt=self.stdout[-TAIL_CHARS:],
            stderr_excerpt=self.stderr[-TAIL_CHARS:],
            stdout_log_path=self.stdout_log_path,
            stderr_log_path=self.stderr_log_path,
        )


class ValidationRunReport(BaseModel):
    label: str
    exit_code: int
    duration_seconds: float
    started_at: str
    ended_at: str
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    stdout_log_path: str = ""
    stderr_log_path: str = ""


class ValidatorRecord(BaseModel):
    verdict: Literal["PASS", "PROGRESS", "SAME_ERROR", "REGRESSION"]
    reason: str
    execution_record: str
    next_focus: str = ""
    latest_validation: ValidationRunReport


class ControllerDecision(BaseModel):
    objective_stage: Literal["PASS", "SPEED", "QUALITY"]
    objective: str
    reason: str
    fix_summary: str = ""
    output_dir: str = ""
    review_video_path: str = ""
    latest_validator_record: ValidatorRecord


class ControllerCycleOutcome(BaseModel):
    action: Literal["CONTINUE", "DONE", "ROLLBACK"]
    objective_stage: Literal["PASS", "SPEED", "QUALITY"]
    objective: str
    reason: str
    fix_summary: str = ""
    output_dir: str = ""
    review_video_path: str = ""
    latest_validator_record: ValidatorRecord
    workers: list[WorkerInvocation] = Field(default_factory=list)


class RollbackRequest(BaseModel):
    head: str
    reason: str


class DoneRequest(BaseModel):
    reason: str


class ReadOnlyFilesystemBackend(FilesystemBackend):
    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=f"Read-only backend: refusing to write {file_path}")

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return self.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=f"Read-only backend: refusing to edit {file_path}")

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return self.edit(file_path, old_string, new_string, replace_all=replace_all)


class ReadOnlyShellBackend(LocalShellBackend):
    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=f"Read-only shell backend: refusing to write {file_path}")

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return self.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=f"Read-only shell backend: refusing to edit {file_path}")

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return self.edit(file_path, old_string, new_string, replace_all=replace_all)


class ValidationCommandRunner:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self._counter = 0
        self.latest_result: ValidationToolResult | None = None

    def run(self, *, attempt_number: int, label: str) -> ValidationToolResult:
        self._counter += 1
        safe_label = _slugify(label or "validation")
        attempt_dir = self.config.log_dir / f"attempt-{attempt_number:04d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{self._counter:02d}-{safe_label}"
        stdout_path = attempt_dir / f"{prefix}.stdout.log"
        stderr_path = attempt_dir / f"{prefix}.stderr.log"

        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        stdout = ""
        stderr = ""
        exit_code = -1
        try:
            result = subprocess.run(
                self.config.target_command,
                shell=True,
                cwd=str(self.config.worktree_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.target_timeout,
                env=self.config.build_env(),
            )
            exit_code = result.returncode
            stdout = result.stdout or ""
            stderr = result.stderr or ""
        except subprocess.TimeoutExpired:
            stderr = f"TIMEOUT after {self.config.target_timeout}s"
        except Exception as exc:  # pragma: no cover - defensive path
            stderr = str(exc)
        duration = perf_counter() - started
        ended_at = datetime.now(timezone.utc)

        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")

        report = ValidationToolResult(
            label=label,
            exit_code=exit_code,
            duration_seconds=duration,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            stdout=stdout,
            stderr=stderr,
            stdout_log_path=str(stdout_path),
            stderr_log_path=str(stderr_path),
        )
        self.latest_result = report
        return report


def _analysis_root(config: ClusterConfig) -> Path:
    return config.cache_root / "analysis" / config.session_id


def _strip_html_tags(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_result_url(raw_url: str) -> str:
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    parsed = urlparse(raw_url)
    if "duckduckgo.com" in parsed.netloc:
        target = parse_qs(parsed.query).get("uddg", [])
        if target:
            return target[0]
    return raw_url


def _parse_search_results(markup: str, max_results: int) -> str:
    matches = re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        markup,
        flags=re.DOTALL,
    )
    lines: list[str] = []
    for idx, match in enumerate(matches, start=1):
        title = _strip_html_tags(match.group("title"))
        snippet = _strip_html_tags(match.group("snippet"))
        url = _normalize_result_url(html.unescape(match.group("href")))
        lines.append(f"Result {idx}\nTitle: {title}\nURL: {url}\nSnippet: {snippet}")
        if idx >= max_results:
            break
    if lines:
        return "\n\n".join(lines)
    fallback = _strip_html_tags(markup)[:WEB_SNIPPET_CHARS]
    return f"No structured search results parsed.\nRaw excerpt:\n{fallback}"


def _compact_memory_text(text: str, limit: int) -> str:
    cleaned = text.replace("\r\n", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    compact = cleaned[: max(limit - 3, 0)].rstrip()
    return compact + "..."


class ValidatorMemoryStore:
    def __init__(self, path: Path, worktree_root: Path):
        self.path = path
        self.worktree_root = worktree_root

    def ensure_exists(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._render_document(current_state=self._render_unvalidated_state(), history=""), encoding="utf-8")

    def record_validation(
        self,
        *,
        attempt_number: int,
        objective_stage: str,
        objective: str,
        record: ValidatorRecord,
    ) -> str:
        self.ensure_exists()
        history = self._extract_history()
        current_state = self._render_fresh_state(attempt_number, objective_stage, objective, record)
        entry = self._render_validation_entry(attempt_number, objective_stage, objective, record)
        updated_history = self._append_history(history, entry)
        self.path.write_text(self._render_document(current_state=current_state, history=updated_history), encoding="utf-8")
        return str(self.path)

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        self.ensure_exists()
        history = self._extract_history()
        entry = (
            f"### Rollback After Attempt {attempt_number}\n"
            f"- Freshness: stale\n"
            f"- Restored worktree head: `{rollback_to or 'unknown'}`\n"
            f"- Reason: {reason or 'The last attempt was discarded by the controller/orchestrator.'}\n"
        )
        current_state = (
            f"- Freshness: stale\n"
            f"- Synced worktree head: `{rollback_to or 'unknown'}`\n"
            "- Note: Python rolled back the last attempt. Run validator again before trusting the current repo state.\n"
        )
        updated_history = self._append_history(history, entry)
        self.path.write_text(self._render_document(current_state=current_state, history=updated_history), encoding="utf-8")

    def _extract_history(self) -> str:
        if not self.path.exists():
            return ""
        text = self.path.read_text(encoding="utf-8")
        marker = "## Execution History"
        if marker not in text:
            return ""
        return text.split(marker, 1)[1].strip()

    def _render_document(self, *, current_state: str, history: str) -> str:
        history_block = history.strip()
        return (
            "# Validator Memory\n\n"
            "## Current Validated State\n"
            f"{current_state.strip()}\n\n"
            "## Execution History\n"
            f"{history_block}\n"
        )

    @staticmethod
    def _append_history(history: str, entry: str) -> str:
        history = history.strip()
        entry = entry.strip()
        if not history:
            return entry
        return f"{history}\n\n{entry}"

    @staticmethod
    def _render_unvalidated_state() -> str:
        return (
            "- Freshness: stale\n"
            "- Synced worktree head: `unknown`\n"
            "- Note: No validator run has established the current repo state yet.\n"
        )

    def _render_fresh_state(
        self,
        attempt_number: int,
        objective_stage: str,
        objective: str,
        record: ValidatorRecord,
    ) -> str:
        run = record.latest_validation
        return (
            "- Freshness: fresh\n"
            f"- Synced worktree head: `{self._current_head()}`\n"
            f"- Attempt: {attempt_number}\n"
            f"- Objective stage: {objective_stage}\n"
            f"- Objective: {objective}\n"
            f"- Label: {run.label}\n"
            f"- Exit code: {run.exit_code}\n"
            f"- Duration seconds: {run.duration_seconds:.2f}\n"
            f"- Verdict: {record.verdict}\n"
            f"- Reason: {record.reason}\n"
            f"- Stdout log: `{run.stdout_log_path}`\n"
            f"- Stderr log: `{run.stderr_log_path}`\n"
            f"- Next focus: {record.next_focus or 'n/a'}\n"
        )

    def _render_validation_entry(
        self,
        attempt_number: int,
        objective_stage: str,
        objective: str,
        record: ValidatorRecord,
    ) -> str:
        run = record.latest_validation
        return (
            f"### Attempt {attempt_number} / {run.label}\n"
            f"- Head: `{self._current_head()}`\n"
            f"- Objective stage: {objective_stage}\n"
            f"- Objective: {objective}\n"
            f"- Exit code: {run.exit_code}\n"
            f"- Duration seconds: {run.duration_seconds:.2f}\n"
            f"- Verdict: {record.verdict}\n"
            f"- Reason: {record.reason}\n"
            f"- Execution record: {record.execution_record}\n"
            f"- Next focus: {record.next_focus or 'n/a'}\n"
            f"- Stdout log: `{run.stdout_log_path}`\n"
            f"- Stderr log: `{run.stderr_log_path}`\n"
        )

    def _current_head(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.worktree_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return result.stdout.strip()
        except Exception:  # pragma: no cover - defensive path
            return "unknown"


class ControllerMemoryStore:
    def __init__(self, path: Path, worktree_root: Path):
        self.path = path
        self.worktree_root = worktree_root

    def ensure_exists(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._render_document(current_state=self._render_empty_state(), history=""), encoding="utf-8")

    def record_strategy(
        self,
        *,
        attempt_number: int,
        objective_stage: str,
        objective: str,
        summary: str,
        next_focus: str,
        discarded_options: str,
        evidence: str,
    ) -> str:
        self.ensure_exists()
        compact_summary = _compact_memory_text(summary, CONTROLLER_MEMORY_SUMMARY_CHARS)
        compact_next_focus = _compact_memory_text(next_focus, CONTROLLER_MEMORY_SHORT_CHARS)
        compact_discarded = _compact_memory_text(discarded_options, CONTROLLER_MEMORY_MEDIUM_CHARS)
        compact_evidence = _compact_memory_text(evidence, CONTROLLER_MEMORY_MEDIUM_CHARS)
        history = self._extract_history()
        current_state = self._render_current_state(
            attempt_number=attempt_number,
            objective_stage=objective_stage,
            objective=objective,
            summary=compact_summary,
            next_focus=compact_next_focus,
            discarded_options=compact_discarded,
            evidence=compact_evidence,
        )
        entry = self._render_history_entry(
            attempt_number=attempt_number,
            objective_stage=objective_stage,
            objective=objective,
            summary=compact_summary,
            next_focus=compact_next_focus,
            discarded_options=compact_discarded,
            evidence=compact_evidence,
        )
        updated_history = self._append_history(history, entry)
        self.path.write_text(self._render_document(current_state=current_state, history=updated_history), encoding="utf-8")
        return str(self.path)

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        self.ensure_exists()
        history = self._extract_history()
        entry = (
            f"### Rollback After Attempt {attempt_number}\n"
            f"- Head restored: `{rollback_to or 'unknown'}`\n"
            f"- Reason: {reason or 'The controller discarded the attempt.'}\n"
            "- Required follow-up: re-evaluate strategy against the restored worktree head before committing to a path.\n"
        )
        current_state = (
            f"- Synced worktree head: `{rollback_to or 'unknown'}`\n"
            "- Strategy status: needs re-evaluation\n"
            f"- Note: Attempt {attempt_number} was rolled back. Treat any strategy tied to the discarded diff as stale until reconfirmed.\n"
        )
        updated_history = self._append_history(history, entry)
        self.path.write_text(self._render_document(current_state=current_state, history=updated_history), encoding="utf-8")

    def record_user_feedback(
        self,
        *,
        attempt_number: int,
        feedback: str,
        video_path: str,
        output_dir: str,
    ) -> None:
        self.ensure_exists()
        compact_feedback = _compact_memory_text(feedback, CONTROLLER_MEMORY_SUMMARY_CHARS)
        history = self._extract_history()
        entry = (
            f"### User Feedback After Attempt {attempt_number}\n"
            f"- Head: `{self._current_head()}`\n"
            f"- Video path: `{video_path or 'unknown'}`\n"
            f"- Output dir: `{output_dir or 'unknown'}`\n"
            f"- Feedback: {compact_feedback or 'n/a'}\n"
        )
        current_state = (
            f"- Synced worktree head: `{self._current_head()}`\n"
            "- Strategy status: incorporate latest user feedback\n"
            f"- Latest review video: `{video_path or 'unknown'}`\n"
            f"- Latest feedback: {compact_feedback or 'n/a'}\n"
        )
        updated_history = self._append_history(history, entry)
        self.path.write_text(self._render_document(current_state=current_state, history=updated_history), encoding="utf-8")

    def _extract_history(self) -> str:
        if not self.path.exists():
            return ""
        text = self.path.read_text(encoding="utf-8")
        marker = "## Decision History"
        if marker not in text:
            return ""
        return text.split(marker, 1)[1].strip()

    def _render_document(self, *, current_state: str, history: str) -> str:
        history_block = history.strip()
        return (
            "# Controller Memory\n\n"
            "## Current Strategic State\n"
            f"{current_state.strip()}\n\n"
            "## Decision History\n"
            f"{history_block}\n"
        )

    @staticmethod
    def _append_history(history: str, entry: str) -> str:
        history = history.strip()
        entry = entry.strip()
        if not history:
            return entry
        return f"{history}\n\n{entry}"

    @staticmethod
    def _render_empty_state() -> str:
        return (
            "- Synced worktree head: `unknown`\n"
            "- Strategy status: unset\n"
            "- Note: No controller strategy snapshot has been recorded yet.\n"
        )

    def _render_current_state(
        self,
        *,
        attempt_number: int,
        objective_stage: str,
        objective: str,
        summary: str,
        next_focus: str,
        discarded_options: str,
        evidence: str,
    ) -> str:
        return (
            f"- Synced worktree head: `{self._current_head()}`\n"
            f"- Attempt: {attempt_number}\n"
            f"- Objective stage: {objective_stage}\n"
            f"- Objective: {objective}\n"
            f"- Strategy summary: {summary}\n"
            f"- Next focus: {next_focus or 'n/a'}\n"
            f"- Discarded options: {discarded_options or 'n/a'}\n"
            f"- Evidence anchors: {evidence or 'n/a'}\n"
        )

    def _render_history_entry(
        self,
        *,
        attempt_number: int,
        objective_stage: str,
        objective: str,
        summary: str,
        next_focus: str,
        discarded_options: str,
        evidence: str,
    ) -> str:
        return (
            f"### Attempt {attempt_number}\n"
            f"- Head: `{self._current_head()}`\n"
            f"- Objective stage: {objective_stage}\n"
            f"- Objective: {objective}\n"
            f"- Strategy summary: {summary}\n"
            f"- Next focus: {next_focus or 'n/a'}\n"
            f"- Discarded options: {discarded_options or 'n/a'}\n"
            f"- Evidence anchors: {evidence or 'n/a'}\n"
        )

    def _current_head(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.worktree_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return result.stdout.strip()
        except Exception:  # pragma: no cover - defensive path
            return "unknown"


CONTROLLER_ROLE = """\
You are the controller for a controller-led multi-agent CI improvement loop.

You are the sole scheduler. Keep improving the target command over repeated attempts.
Your priority order is:
1. PASS: make the target command pass.
2. SPEED: once it passes, improve runtime without breaking behavior.
3. QUALITY: once it passes and speed gains are small, improve maintainability without regressions.

You are allowed to pursue improvements at multiple levels:
- local code fixes
- pipeline or architecture changes
- dependency changes
- model/provider changes, including audio-related models and services
- caching, batching, concurrency, and execution-strategy changes

Hard rules:
- You never modify code directly.
- You never run the target command directly.
- Use the `explore` subagent for read-only codebase search, repository understanding, and lightweight evidence gathering.
- Use the `task` subagent for broader multi-step exploration that may need shell commands, external references, or chained investigation.
- Delegate all code changes to the `fixer` subagent.
- Delegate all target-command execution to the `validator` subagent.
- Controller memory is your durable strategy ledger for objective framing, discarded paths, and next-step criteria.
- The validator memory is the durable record of the last validated repo state.
- When you learn something that should survive long-running exploration, write controller memory before moving on.
- Before a long exploratory branch, before calling `request_done`, and before calling `request_rollback`, update controller memory.
- Keep controller memory terse. Write only durable facts, decisions, discarded paths, and next-step criteria. Do not dump long narratives, logs, or transcripts into memory.
- If validator memory is stale, missing, or synced to a different HEAD than the current worktree HEAD, call `validator` first.
- After any fixer delegation, call `validator` again before you return.
- Explore boldly, verify carefully, and do not lock onto a direction without evidence.
- Use only the `explore`, `task`, `fixer`, and `validator` subagents.
- Do not use the default `general-purpose` subagent; use `task` or `explore` explicitly instead.
- Do not be artificially conservative. If a dependency, architecture, or model-level change is the best path, pursue it.
- Prefer the smallest sufficient change, not the smallest possible diff.
- Controller memory entries should be compact: short bullets or short paragraphs, focused on what must survive context compression.
- Before calling `request_done`, you must ensure there is at least one completed, reviewable video artifact from the current repo state.
- Your structured response must include `output_dir` and `review_video_path` when a completed artifact exists.
- If you call `request_done`, `review_video_path` must point to the review artifact you want Python to send to the user.
- If the current attempt should be discarded, you must call the `request_rollback` tool. Do not encode rollback only in structured output.
- If the current validated state is good enough to stop, you must call the `request_done` tool. Do not encode done only in structured output.

Decision rules:
- Call `request_rollback` when the latest validator result shows the same root cause or a regression that should be discarded.
- Call `request_done` only when the current repo state is good enough to stop improving for now.
- If neither request is made, Python will treat the attempt as `CONTINUE`.

Your final structured response must include the latest validator record from the current repo state.
Your final structured response should include the current output directory and the latest reviewable video path whenever they are known.
Your structured response must not contain an action field. Done and rollback are requested via tools.
"""


EXPLORE_ROLE = """\
You are the Explore subagent for a controller-led CI loop.

Your job is to search and understand without making changes.

You may:
- inspect repository code and project files
- analyze product behavior and feature flow
- search the web
- fetch remote pages

Rules:
- Do not modify repository code.
- Do not run the target command; validator owns that.
- Do not use shell commands.
- Focus on code search, repository understanding, external reading, and evidence gathering.
- Return concise findings, relevant file references, and open questions for the controller.
"""


TASK_ROLE = """\
You are the Task subagent for a controller-led CI loop.

Your job is to handle broader, multi-step exploratory work before code is changed.

You may:
- analyze feasibility and compare approaches
- compare architecture options
- evaluate dependency replacements
- evaluate model/provider changes, especially audio-related ones
- search the web
- fetch remote pages
- execute shell commands for exploration, including cloning reference repositories into the dedicated analysis workspace

Rules:
- Do not modify repository code.
- Do not run the target command; validator owns that.
- You have shell access. Use it boldly for investigation, prototyping, and gathering references.
- Shell starts in the analysis workspace. Useful environment variables include `CI_AGENT_SOURCE_ROOT`, `CI_AGENT_WORKTREE_ROOT`, and `CI_AGENT_ANALYSIS_ROOT`.
- If you clone external repositories or download artifacts, keep them under the analysis workspace instead of the main repository.
- Return concrete findings, tradeoffs, and a recommended next move for the controller.
"""


FIXER_ROLE = """\
You are the fixer subagent inside an isolated CI worktree branch.

Your job is to make coherent code changes that advance the controller's objective.

Rules:
- You are the only agent allowed to modify repository files.
- Prefer the smallest sufficient change set that clearly advances the current objective.
- If the root cause or optimization opportunity is architectural, dependency-related, or model/provider-related, you may make structural changes instead of forcing a narrow patch.
- Read relevant files before editing them.
- Re-read changed files after editing.
- Use uv for dependency changes.
- Never run `git add .`.
- Commit only targeted, coherent changes.
- Commit message format: `fix(<scope>): <description>`.
- Do not run the full target command as final validation; the validator owns that.
- If you cannot justify a code change, say so directly instead of fabricating work.
"""


VALIDATOR_ROLE = """\
You are the validator subagent for a controller-led CI loop.

You are the only agent allowed to execute the target command, and you must do it by calling the `run_validation_command` tool.
You must update persistent validator memory by calling `record_validator_memory` after every validation run.
You never edit repository code.

Use the latest validation result and repository context to decide one of these verdicts:
- PASS: the target command passes and the current state is acceptable.
- PROGRESS: the system moved forward materially, but more work is still worthwhile.
- SAME_ERROR: the same root cause remains; the last fix should be discarded.
- REGRESSION: the new state is worse or broke a previously green target.

Your final response must be strict JSON matching this schema:
{
  "verdict": "PASS|PROGRESS|SAME_ERROR|REGRESSION",
  "reason": "short explanation",
  "execution_record": "concise narrative of what was run and why this verdict was chosen",
  "next_focus": "recommended next focus or empty string",
  "latest_validation": {
    "label": "validation label",
    "exit_code": 0,
    "duration_seconds": 0.0,
    "started_at": "ISO timestamp",
    "ended_at": "ISO timestamp",
    "stdout_excerpt": "tail of stdout",
    "stderr_excerpt": "tail of stderr",
    "stdout_log_path": "path",
    "stderr_log_path": "path"
  }
}
"""


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "validation"


def _extract_worker(worker_type: str, prompt: str, result: dict) -> WorkerInvocation:
    tool_calls: list[ToolCallRecord] = []
    tool_results: dict[str, str] = {}
    final_text = ""

    for message in result.get("messages", []):
        if isinstance(message, AIMessage):
            text = _message_text(message).strip()
            if text:
                final_text = text
            for tool_call in message.tool_calls:
                tool_name = str(tool_call.get("name", "unknown"))
                tool_input = tool_call.get("args", {}) or {}
                tool_calls.append(ToolCallRecord(tool_name=tool_name, tool_input=tool_input))
        elif isinstance(message, ToolMessage):
            tool_name = getattr(message, "name", "") or "unknown"
            tool_results[tool_name] = _message_text(message).strip()

    for call in tool_calls:
        summary = tool_results.get(call.tool_name, "")
        call.result_summary = summary[:500]
        lowered = summary.lower()
        if "error" in lowered or "failed" in lowered:
            call.success = False

    return WorkerInvocation(
        worker_type=worker_type,
        prompt_summary=prompt[:500],
        tool_calls=tool_calls,
        final_text=final_text[:4000],
    )


def _extract_workers(prompt: str, result: dict) -> list[WorkerInvocation]:
    workers: list[WorkerInvocation] = [_extract_worker("controller", prompt, result)]
    pending_tasks: list[tuple[str, str]] = []

    for message in result.get("messages", []):
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                if str(tool_call.get("name")) == "task":
                    args = tool_call.get("args", {}) or {}
                    pending_tasks.append(
                        (
                            str(args.get("subagent_type", "subagent")),
                            str(args.get("description", ""))[:500],
                        )
                    )
        elif isinstance(message, ToolMessage) and (getattr(message, "name", "") or "") == "task":
            description = ""
            worker_type = "subagent"
            if pending_tasks:
                worker_type, description = pending_tasks.pop(0)
            workers.append(
                WorkerInvocation(
                    worker_type=worker_type,
                    prompt_summary=description,
                    final_text=_message_text(message).strip()[:4000],
                )
            )

    return workers


def _parse_structured_response(result: dict, schema: type[BaseModel]) -> BaseModel | None:
    structured = result.get("structured_response")
    if isinstance(structured, schema):
        return structured
    if isinstance(structured, dict):
        return schema.model_validate(structured)
    return None


def _default_validator_record(report: ValidationToolResult | None) -> ValidatorRecord:
    if report is None:
        summary = ValidationRunReport(
            label="validation-missing",
            exit_code=-1,
            duration_seconds=0.0,
            started_at=datetime.now(timezone.utc).isoformat(),
            ended_at=datetime.now(timezone.utc).isoformat(),
        )
    else:
        summary = report.to_summary()
    return ValidatorRecord(
        verdict="SAME_ERROR",
        reason="Controller did not return a structured validator record.",
        execution_record="No reliable validator record was returned to Python.",
        next_focus="Run validator again before trusting the repo state.",
        latest_validation=summary,
    )


def _resolve_cycle_action(
    rollback_request: RollbackRequest | None,
    done_request: DoneRequest | None,
) -> Literal["CONTINUE", "DONE", "ROLLBACK"]:
    if rollback_request is not None:
        return "ROLLBACK"
    if done_request is not None:
        return "DONE"
    return "CONTINUE"


class DeepAgentRuntime:
    def __init__(self, config: ClusterConfig):
        self.config = config
        self._validator_memory_store = ValidatorMemoryStore(config.validator_memory_file, config.worktree_root)
        self._controller_memory_store = ControllerMemoryStore(config.controller_memory_file, config.worktree_root)

    async def run_controller_cycle(self, prompt: str, *, attempt_number: int) -> ControllerCycleOutcome:
        self._validator_memory_store.ensure_exists()
        self._controller_memory_store.ensure_exists()
        runner = ValidationCommandRunner(self.config)
        analysis_root = _analysis_root(self.config)
        analysis_root.mkdir(parents=True, exist_ok=True)
        worker_model = self.config.build_worker_model()
        rollback_request: RollbackRequest | None = None
        done_request: DoneRequest | None = None

        @tool(parse_docstring=True)
        def search_web(query: str, max_results: int = 5) -> str:
            """Search the public web for a query and return summarized results.

            Args:
                query: Search query string.
                max_results: Maximum number of parsed results to return.
            """

            safe_results = min(max(max_results, 1), 8)
            request = Request(
                "https://html.duckduckgo.com/html/?q=" + query.replace(" ", "+"),
                headers={"User-Agent": "Mozilla/5.0 (compatible; ci-agent/1.0)"},
            )
            try:
                with urlopen(request, timeout=20) as response:
                    markup = response.read().decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError) as exc:
                return f"Web search failed for query {query!r}: {exc}"
            return _parse_search_results(markup, safe_results)

        @tool(parse_docstring=True)
        def fetch_web_page(url: str, max_chars: int = WEB_SNIPPET_CHARS) -> str:
            """Fetch a web page and return a text excerpt.

            Args:
                url: Absolute URL to fetch.
                max_chars: Maximum characters to return from the page body.
            """

            request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ci-agent/1.0)"})
            try:
                with urlopen(request, timeout=20) as response:
                    final_url = response.geturl()
                    body = response.read().decode("utf-8", errors="replace")
                    content_type = response.headers.get_content_type()
            except (HTTPError, URLError, TimeoutError) as exc:
                return f"Fetch failed for {url}: {exc}"
            excerpt = body[: max(1000, min(max_chars, 20000))]
            return (
                f"Fetched: {final_url}\n"
                f"Content-Type: {content_type}\n"
                f"Excerpt:\n{excerpt}"
            )

        @tool(parse_docstring=True)
        def run_validation_command(label: str) -> str:
            """Run the configured target command and return full logs plus timing information.

            Args:
                label: Short label describing why this validation run is happening.
            """

            report = runner.run(attempt_number=attempt_number, label=label)
            return report.model_dump_json(indent=2)

        @tool(parse_docstring=True)
        def record_validator_memory(record_json: str, objective_stage: str, objective: str) -> str:
            """Persist the latest validator decision into session-scoped validator memory.

            Args:
                record_json: Strict JSON for a ValidatorRecord object.
                objective_stage: Current objective stage such as PASS, SPEED, or QUALITY.
                objective: Current optimization objective.
            """

            record = ValidatorRecord.model_validate_json(record_json)
            path = self._validator_memory_store.record_validation(
                attempt_number=attempt_number,
                objective_stage=objective_stage,
                objective=objective,
                record=record,
            )
            return f"Validator memory updated at {path}"

        @tool(parse_docstring=True)
        def record_controller_memory(
            objective_stage: str,
            objective: str,
            summary: str,
            next_focus: str = "",
            discarded_options: str = "",
            evidence: str = "",
        ) -> str:
            """Persist concise controller strategy notes into session-scoped controller memory.

            Args:
                objective_stage: Current objective stage such as PASS, SPEED, or QUALITY.
                objective: Current optimization objective.
                summary: Short durable summary of the current strategy and reasoning.
                next_focus: Short next focus or decision criterion.
                discarded_options: Short note on options ruled out and why.
                evidence: Key evidence anchors, file paths, or external references.
            """

            path = self._controller_memory_store.record_strategy(
                attempt_number=attempt_number,
                objective_stage=objective_stage,
                objective=objective,
                summary=summary.strip(),
                next_focus=next_focus.strip(),
                discarded_options=discarded_options.strip(),
                evidence=evidence.strip(),
            )
            return f"Controller memory updated at {path}"

        @tool(parse_docstring=True)
        def request_rollback(head: str, reason: str) -> str:
            """Request that Python safely roll back the current attempt to a known worktree head.

            Args:
                head: The worktree HEAD to restore, typically the head recorded at the start of the attempt.
                reason: Why the current attempt should be discarded.
            """

            nonlocal rollback_request
            rollback_request = RollbackRequest(head=head.strip(), reason=reason.strip())
            return f"Recorded rollback request for head {rollback_request.head or 'unknown'}"

        @tool(parse_docstring=True)
        def request_done(reason: str) -> str:
            """Request that Python finish the session with the current validated state.

            Args:
                reason: Why the controller believes the current validated state is sufficient to stop.
            """

            nonlocal done_request
            done_request = DoneRequest(reason=reason.strip())
            return "Recorded done request"

        explore = create_deep_agent(
            model=worker_model,
            system_prompt=EXPLORE_ROLE,
            backend=ReadOnlyFilesystemBackend(
                root_dir=self.config.project_root,
                virtual_mode=True,
            ),
            tools=[search_web, fetch_web_page],
            memory=[str(self.config.runbook_file)],
            name="ci-agent-explore",
        )
        task = create_deep_agent(
            model=worker_model,
            system_prompt=TASK_ROLE,
            backend=ReadOnlyShellBackend(
                root_dir=analysis_root,
                virtual_mode=True,
                inherit_env=True,
                env=self.config.build_env(),
            ),
            tools=[search_web, fetch_web_page],
            memory=[str(self.config.runbook_file)],
            name="ci-agent-task",
        )
        fixer = create_deep_agent(
            model=worker_model,
            system_prompt=FIXER_ROLE,
            backend=LocalShellBackend(
                root_dir=self.config.worktree_root,
                virtual_mode=True,
                inherit_env=True,
                env=self.config.build_env(),
            ),
            memory=[str(self.config.runbook_file)],
            name="ci-agent-fixer",
        )
        validator = create_deep_agent(
            model=worker_model,
            system_prompt=VALIDATOR_ROLE,
            backend=ReadOnlyFilesystemBackend(
                root_dir=self.config.project_root,
                virtual_mode=True,
            ),
            tools=[run_validation_command, record_validator_memory],
            memory=[str(self.config.runbook_file), str(self.config.validator_memory_file)],
            name="ci-agent-validator",
        )
        controller = create_deep_agent(
            model=self.config.model,
            system_prompt=CONTROLLER_ROLE,
            backend=ReadOnlyFilesystemBackend(
                root_dir=self.config.project_root,
                virtual_mode=True,
            ),
            subagents=[
                CompiledSubAgent(
                    name="explore",
                    description=(
                        "Read-only exploration helper for repository understanding, code search, and external reading."
                    ),
                    runnable=explore,
                ),
                CompiledSubAgent(
                    name="task",
                    description=(
                        "General-purpose multi-step helper for exploratory shell work, reference gathering, and "
                        "broader feasibility analysis."
                    ),
                    runnable=task,
                ),
                CompiledSubAgent(
                    name="fixer",
                    description="Modify repository code inside the isolated worktree and optionally commit targeted changes.",
                    runnable=fixer,
                ),
                CompiledSubAgent(
                    name="validator",
                    description="Run the wrapped validation command, update validator memory, and return a strict JSON validation record.",
                    runnable=validator,
                ),
            ],
            memory=[
                str(self.config.runbook_file),
                str(self.config.controller_memory_file),
                str(self.config.validator_memory_file),
            ],
            tools=[request_rollback, request_done, record_controller_memory],
            response_format=ToolStrategy(schema=ControllerDecision),
            name="ci-agent-controller",
        )

        result = await controller.ainvoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max(80, self.config.max_worker_turns * 6)},
        )

        workers = _extract_workers(prompt, result)
        structured = _parse_structured_response(result, ControllerDecision)
        if isinstance(structured, ControllerDecision):
            latest_record = structured.latest_validator_record
            resolved_action = _resolve_cycle_action(rollback_request, done_request)
            if rollback_request is not None and rollback_request.reason:
                resolved_reason = rollback_request.reason
            elif done_request is not None and done_request.reason:
                resolved_reason = done_request.reason
            else:
                resolved_reason = structured.reason
            outcome = ControllerCycleOutcome(
                action=resolved_action,
                objective_stage=structured.objective_stage,
                objective=structured.objective,
                reason=resolved_reason,
                fix_summary=structured.fix_summary,
                output_dir=structured.output_dir,
                review_video_path=structured.review_video_path,
                latest_validator_record=latest_record,
                workers=workers,
            )
        else:
            logger.warning("Controller returned no structured response, defaulting to rollback")
            latest_record = _default_validator_record(runner.latest_result)
            resolved_action = "ROLLBACK"
            resolved_reason = (
                rollback_request.reason
                if rollback_request is not None and rollback_request.reason
                else "Controller response was not structured."
            )
            outcome = ControllerCycleOutcome(
                action=resolved_action,
                objective_stage="PASS",
                objective="Re-establish a trustworthy validated state.",
                reason=resolved_reason,
                fix_summary="",
                output_dir="",
                review_video_path="",
                latest_validator_record=latest_record,
                workers=workers,
            )

        if outcome.workers:
            outcome.workers[0].final_text = (
                f"action={outcome.action}; stage={outcome.objective_stage}; objective={outcome.objective}; reason={outcome.reason}"
            )[:4000]
        return outcome

    def note_rollback(self, *, attempt_number: int, rollback_to: str, reason: str) -> None:
        self._validator_memory_store.note_rollback(attempt_number=attempt_number, rollback_to=rollback_to, reason=reason)
        self._controller_memory_store.note_rollback(attempt_number=attempt_number, rollback_to=rollback_to, reason=reason)

    def note_user_feedback(self, *, attempt_number: int, feedback: str, video_path: str, output_dir: str) -> None:
        self._controller_memory_store.record_user_feedback(
            attempt_number=attempt_number,
            feedback=feedback,
            video_path=video_path,
            output_dir=output_dir,
        )
