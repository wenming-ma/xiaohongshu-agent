from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    path: Path
    body: str


class ProjectSkillRegistry:
    def __init__(self, *, skills_root: Path):
        self.skills_root = skills_root
        self._skills: list[SkillSpec] | None = None

    def discover(self) -> list[SkillSpec]:
        if self._skills is not None:
            return self._skills

        skills: list[SkillSpec] = []
        if not self.skills_root.exists():
            self._skills = []
            return self._skills

        for skill_file in sorted(self.skills_root.glob("*/SKILL.md")):
            raw = skill_file.read_text(encoding="utf-8")
            frontmatter, body = self._split_frontmatter(raw)
            name = str(frontmatter.get("name") or skill_file.parent.name).strip()
            description = str(frontmatter.get("description") or "").strip()
            if not name or not description:
                continue
            skills.append(
                SkillSpec(
                    name=name,
                    description=description,
                    path=skill_file.parent,
                    body=body.strip(),
                )
            )

        self._skills = sorted(skills, key=lambda item: item.name)
        return self._skills

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict, str]:
        if not raw.startswith("---\n"):
            return {}, raw

        end_idx = raw.find("\n---\n", 4)
        if end_idx == -1:
            return {}, raw

        frontmatter = yaml.safe_load(raw[4:end_idx]) or {}
        body = raw[end_idx + 5 :]
        return frontmatter, body
