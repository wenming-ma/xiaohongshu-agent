from __future__ import annotations

from pathlib import Path


class AgentOSResourceTools:
    def __init__(self, *, skills_root: Path, prompt_root: Path) -> None:
        self.skills_root = Path(skills_root)
        self.prompt_root = Path(prompt_root)

    def list_skills(self) -> list[dict[str, str]]:
        if not self.skills_root.exists():
            return []
        return [
            {"name": skill_file.parent.name, "path": str(skill_file)}
            for skill_file in sorted(self.skills_root.glob("*/SKILL.md"))
        ]

    def read_skill(self, name: str) -> str:
        path = self.skills_root / name / "SKILL.md"
        return path.read_text(encoding="utf-8")

    def search_prompt_templates(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, int | str]]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not self.prompt_root.exists() or not terms:
            return []

        scored: list[dict[str, int | str]] = []
        for path in sorted(self.prompt_root.rglob("*.md")):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            score = sum(1 for term in terms if term in text)
            if score:
                scored.append({"path": str(path), "score": score})
        return sorted(scored, key=lambda item: (-int(item["score"]), str(item["path"])))[:limit]

    def read_prompt_template(self, path: str) -> str:
        candidate = Path(path)
        resolved = candidate.resolve()
        root = self.prompt_root.resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError(f"Prompt template path is outside prompt root: {path}")
        return resolved.read_text(encoding="utf-8")
