from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend, LocalShellBackend
from deepagents.backends.protocol import EditResult, WriteResult
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel

from .config import ClusterConfig
from .state import ToolCallRecord, WorkerInvocation

logger = logging.getLogger(__name__)


class ValidationVerdict(BaseModel):
    verdict: Literal["SAME_ERROR", "PROGRESS"]
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


class ValidationOutcome(BaseModel):
    verdict: Literal["SAME_ERROR", "PROGRESS"]
    reason: str
    worker: WorkerInvocation


FIXER_ROLE = """\
You are an autonomous CI fixer operating inside a dedicated git worktree for a Xiaohongshu video post pipeline.

Your goals:
1. Analyze the failing run output and inspect the relevant files.
2. Make the smallest change that fixes the failure.
3. Re-read changed files to verify the edit.
4. If your change is worth keeping, create a precise git commit on the current worktree branch.

Rules:
- Never assume you are on main; you are always inside an isolated worktree branch.
- Do not touch unrelated code or perform broad refactors.
- Use uv for Python dependency changes.
- Never use `git add .`; stage specific files only.
- Commit message format: `fix(<scope>): <description>`.
- If no useful change can be made, explain why instead of fabricating a fix.
"""

VALIDATOR_ROLE = """\
You are a senior engineer validating whether a fix attempt made real progress.

Read files when necessary, but do not modify files or run commands.
Return a structured verdict:
- SAME_ERROR: the root cause is unchanged, so the fix should be discarded.
- PROGRESS: the error moved, changed materially, or the system advanced.
"""


def _load_runbook(path: Path) -> str:
    if not path.exists():
        logger.warning("CI agent runbook missing at %s", path)
        return ""
    return path.read_text(encoding="utf-8").strip()


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


class DeepAgentRuntime:
    def __init__(self, config: ClusterConfig):
        runbook = _load_runbook(config.runbook_file)
        shared_prompt = f"{runbook}\n\n" if runbook else ""
        self.config = config
        self._fixer = create_deep_agent(
            model=config.model,
            system_prompt=shared_prompt + FIXER_ROLE,
            backend=LocalShellBackend(
                root_dir=config.worktree_root,
                virtual_mode=True,
                inherit_env=True,
                env=config.build_env(),
            ),
        )
        self._validator = create_deep_agent(
            model=config.model,
            system_prompt=shared_prompt + VALIDATOR_ROLE,
            backend=ReadOnlyFilesystemBackend(
                root_dir=config.worktree_root,
                virtual_mode=True,
            ),
            response_format=ToolStrategy(schema=ValidationVerdict),
        )

    async def run_fixer(self, prompt: str) -> WorkerInvocation:
        result = await self._fixer.ainvoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max(50, self.config.max_worker_turns * 4)},
        )
        return _extract_worker("fixer", prompt, result)

    async def run_validator(self, prompt: str) -> ValidationOutcome:
        result = await self._validator.ainvoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max(30, self.config.max_worker_turns * 2)},
        )
        worker = _extract_worker("validator", prompt, result)
        structured = result.get("structured_response")
        if isinstance(structured, ValidationVerdict):
            verdict = structured.verdict
            reason = structured.reason
        else:
            logger.warning("Validator returned no structured response, defaulting to PROGRESS")
            verdict = "PROGRESS"
            reason = "Validator response was not structured."
        return ValidationOutcome(verdict=verdict, reason=reason, worker=worker)
