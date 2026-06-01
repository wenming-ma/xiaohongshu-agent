from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .schemas import AgentToolResult


class AgentToolContext(BaseModel):
    run_id: str
    task_id: str | None = None
    step_id: str | None = None
    chat_id: str | None = None
    session: Any | None = None
    workspace_dir: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


AgentToolExecute = Callable[..., Awaitable[AgentToolResult]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    execute: AgentToolExecute
    category: str = "specialist"
    resource_group: str | None = None


@dataclass
class AgentToolRegistry:
    _tools: dict[str, AgentTool] = field(default_factory=dict)

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate Agent OS tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> AgentTool:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent OS tool: {tool_name}") from exc

    def describe_tools(self) -> list[dict[str, str]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self,
        tool_name: str,
        ctx: AgentToolContext,
        /,
        **params: Any,
    ) -> AgentToolResult:
        tool = self.get(tool_name)
        return await tool.execute(ctx, **params)
