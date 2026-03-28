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


class ObjectiveDecision(BaseModel):
    stage: Literal["PASS", "SPEED", "QUALITY", "DONE"]
    objective: str
    reason: str
    fixer_system_overlay: str = ""
    validator_system_overlay: str = ""


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


class ControllerOutcome(BaseModel):
    stage: Literal["PASS", "SPEED", "QUALITY", "DONE"]
    objective: str
    reason: str
    fixer_system_overlay: str = ""
    validator_system_overlay: str = ""
    worker: WorkerInvocation


CONTROLLER_ROLE = """\
You are the higher-level CI objective controller for a Xiaohongshu video post pipeline.

Choose the single current optimization stage for the fixer agent.

Priority order:
1. PASS: the target command must pass before anything else matters.
2. SPEED: only after the target command passes; reduce runtime while preserving behavior.
3. QUALITY: only after the target command passes and speed work has reached diminishing returns; improve maintainability, clarity, and safety without regressing behavior or speed materially.
4. DONE: only when the current baseline is good enough and no further worthwhile optimization is justified right now.

Rules:
- If the latest target run failed, return PASS.
- Do not skip straight to QUALITY when PASS is not already satisfied.
- Be conservative about DONE; choose it only when the recent history suggests further edits are low value or risky.
- Return a specific objective sentence the fixer can execute in one attempt.
- Also return `fixer_system_overlay` and `validator_system_overlay`.
- These overlays are temporary system-level operating instructions for this attempt.
- You may change strategy between attempts, but you must still respect repository safety and worktree isolation.
"""


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


def _parse_structured_response(result: dict, schema: type[BaseModel]) -> BaseModel | None:
    structured = result.get("structured_response")
    if isinstance(structured, schema):
        return structured
    if isinstance(structured, dict):
        return schema.model_validate(structured)
    return None


def _build_system_prompt(shared_prompt: str, role_prompt: str, overlay: str = "") -> str:
    if not overlay.strip():
        return shared_prompt + role_prompt
    return (
        shared_prompt
        + role_prompt
        + "\n\nController directive for this attempt:\n"
        + overlay.strip()
        + "\n\nYou must follow this directive unless it conflicts with repository safety rules above."
    )


class DeepAgentRuntime:
    def __init__(self, config: ClusterConfig):
        runbook = _load_runbook(config.runbook_file)
        self._shared_prompt = f"{runbook}\n\n" if runbook else ""
        self.config = config
        self._controller = create_deep_agent(
            model=config.model,
            system_prompt=_build_system_prompt(self._shared_prompt, CONTROLLER_ROLE),
            backend=ReadOnlyFilesystemBackend(
                root_dir=config.worktree_root,
                virtual_mode=True,
            ),
            response_format=ToolStrategy(schema=ObjectiveDecision),
        )

    def _create_fixer(self, overlay: str):
        return create_deep_agent(
            model=self.config.model,
            system_prompt=_build_system_prompt(self._shared_prompt, FIXER_ROLE, overlay),
            backend=LocalShellBackend(
                root_dir=self.config.worktree_root,
                virtual_mode=True,
                inherit_env=True,
                env=self.config.build_env(),
            ),
        )

    def _create_validator(self, overlay: str):
        return create_deep_agent(
            model=self.config.model,
            system_prompt=_build_system_prompt(self._shared_prompt, VALIDATOR_ROLE, overlay),
            backend=ReadOnlyFilesystemBackend(
                root_dir=self.config.worktree_root,
                virtual_mode=True,
            ),
            response_format=ToolStrategy(schema=ValidationVerdict),
        )

    async def run_controller(self, prompt: str) -> ControllerOutcome:
        result = await self._controller.ainvoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max(20, self.config.max_worker_turns * 2)},
        )
        worker = _extract_worker("controller", prompt, result)
        structured = _parse_structured_response(result, ObjectiveDecision)
        if isinstance(structured, ObjectiveDecision):
            stage = structured.stage
            objective = structured.objective
            reason = structured.reason
            fixer_system_overlay = structured.fixer_system_overlay
            validator_system_overlay = structured.validator_system_overlay
        else:
            logger.warning("Controller returned no structured response, defaulting to PASS")
            stage = "PASS"
            objective = "Make the target command pass."
            reason = "Controller response was not structured."
            fixer_system_overlay = "Focus narrowly on restoring a passing target command."
            validator_system_overlay = "Judge only whether the target command meaningfully improved."
        return ControllerOutcome(
            stage=stage,
            objective=objective,
            reason=reason,
            fixer_system_overlay=fixer_system_overlay,
            validator_system_overlay=validator_system_overlay,
            worker=worker,
        )

    async def run_fixer(self, prompt: str, system_overlay: str = "") -> WorkerInvocation:
        fixer = self._create_fixer(system_overlay)
        result = await fixer.ainvoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max(50, self.config.max_worker_turns * 4)},
        )
        return _extract_worker("fixer", prompt, result)

    async def run_validator(self, prompt: str, system_overlay: str = "") -> ValidationOutcome:
        validator = self._create_validator(system_overlay)
        result = await validator.ainvoke(
            {"messages": [("user", prompt)]},
            config={"recursion_limit": max(30, self.config.max_worker_turns * 2)},
        )
        worker = _extract_worker("validator", prompt, result)
        structured = _parse_structured_response(result, ValidationVerdict)
        if isinstance(structured, ValidationVerdict):
            verdict = structured.verdict
            reason = structured.reason
        else:
            logger.warning("Validator returned no structured response, defaulting to PROGRESS")
            verdict = "PROGRESS"
            reason = "Validator response was not structured."
        return ValidationOutcome(verdict=verdict, reason=reason, worker=worker)
