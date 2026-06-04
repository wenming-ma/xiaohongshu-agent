from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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
