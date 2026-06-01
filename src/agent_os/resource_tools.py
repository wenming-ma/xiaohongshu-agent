from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any


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

    def list_local_files(
        self,
        path: str,
        *,
        glob: str = "*",
        recursive: bool = False,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Local path does not exist: {path}")

        candidates = [root] if root.is_file() else (
            root.rglob(glob) if recursive else root.glob(glob)
        )
        files: list[dict[str, Any]] = []
        for candidate in sorted(candidates):
            resolved = candidate.resolve()
            mime_type, _ = mimetypes.guess_type(str(resolved))
            files.append(
                {
                    "path": str(resolved),
                    "name": resolved.name,
                    "type": "directory" if resolved.is_dir() else "file",
                    "size": 0 if resolved.is_dir() else resolved.stat().st_size,
                    "mime_type": mime_type or "",
                }
            )
            if len(files) >= max(1, min(limit, 500)):
                break
        return files

    def read_local_text_file(self, path: str, *, max_chars: int = 12000) -> str:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Local text file does not exist: {path}")
        text = resolved.read_text(encoding="utf-8", errors="ignore")
        return text[: max(1, max_chars)]
