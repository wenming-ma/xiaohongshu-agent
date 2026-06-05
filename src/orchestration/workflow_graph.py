from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from .schemas import ResultEnvelope, WorkflowState


class ModuleNodeSpec(BaseModel):
    """Public boundary for one executable workflow module."""

    name: str
    input_refs: list[str] = Field(default_factory=list)
    output_ref: str
    subnodes: list[str] = Field(default_factory=list)
    subgraphs: dict[str, list[str]] = Field(default_factory=dict)
    supports_parallel: bool = False

    def describe(self) -> dict[str, object]:
        description: dict[str, object] = {
            "name": self.name,
            "input_refs": list(self.input_refs),
            "output_ref": self.output_ref,
            "subnodes": list(self.subnodes),
            "supports_parallel": self.supports_parallel,
        }
        if self.subgraphs:
            description["subgraphs"] = {
                name: list(nodes)
                for name, nodes in self.subgraphs.items()
            }
        return description


class ModuleGraphSpec(BaseModel):
    """Declarative module graph contract for orchestration tests and docs."""

    name: str
    modules: list[ModuleNodeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_duplicate_modules(self) -> "ModuleGraphSpec":
        seen: set[str] = set()
        for module in self.modules:
            if module.name in seen:
                raise ValueError(f"Duplicate module node: {module.name}")
            seen.add(module.name)
        return self

    @property
    def module_names(self) -> list[str]:
        return [module.name for module in self.modules]

    def get(self, name: str) -> ModuleNodeSpec:
        for module in self.modules:
            if module.name == name:
                return module
        raise KeyError(f"Unknown module node: {name}")

    def describe(self) -> list[dict[str, object]]:
        return [module.describe() for module in self.modules]


@runtime_checkable
class ModuleNode(Protocol):
    """Executable module boundary used by application-level orchestrators.

    Pydantic Graph nodes can still be used inside a module. This protocol is the
    outer contract: consume a shared WorkflowState and return a ResultEnvelope.
    """

    spec: ModuleNodeSpec

    async def run(self, state: WorkflowState) -> ResultEnvelope[Any]: ...


@dataclass(frozen=True)
class FunctionModuleNode:
    """Adapter for simple function-backed modules in tests and lightweight flows."""

    spec: ModuleNodeSpec
    handler: Callable[[WorkflowState], Awaitable[ResultEnvelope[Any]]]

    async def run(self, state: WorkflowState) -> ResultEnvelope[Any]:
        return await self.handler(state)


class ModuleGraph:
    """Minimal executable ordered module graph.

    The formal specialist routes still use pydantic_graph for rich internals.
    This class defines the shared application-layer contract for modules that
    are already coarse-grained: every node receives WorkflowState, writes one
    ResultEnvelope under its declared output_ref, and downstream nodes only read
    prior module refs.
    """

    def __init__(
        self,
        *,
        spec: ModuleGraphSpec,
        nodes: Sequence[ModuleNode],
    ) -> None:
        self.spec = spec
        self.nodes_by_name = {node.spec.name: node for node in nodes}
        missing = [module.name for module in spec.modules if module.name not in self.nodes_by_name]
        if missing:
            raise ValueError(f"Missing module implementations: {', '.join(missing)}")

    async def run(self, state: WorkflowState) -> WorkflowState:
        for module_spec in self.spec.modules:
            self._assert_inputs_available(state, module_spec)
            node = self.nodes_by_name[module_spec.name]
            result = await node.run(state)
            state.module_results[module_spec.output_ref] = result
        return state

    @staticmethod
    def _assert_inputs_available(state: WorkflowState, module_spec: ModuleNodeSpec) -> None:
        available_refs = {"workflow_invocation", *state.module_results.keys()}
        missing = [ref for ref in module_spec.input_refs if ref not in available_refs]
        if missing:
            raise ValueError(
                f"Module `{module_spec.name}` missing input refs: {', '.join(missing)}"
            )
