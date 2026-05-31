from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import yaml


_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if len(token.strip()) > 1
    }


def _bigrams(text: str) -> set[str]:
    normalized = "".join(_TOKEN_RE.findall(text.lower()))
    return {
        normalized[idx : idx + 2]
        for idx in range(len(normalized) - 1)
        if normalized[idx : idx + 2].strip()
    }


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

    def match(self, query: str, *, limit: int = 3) -> list[SkillSpec]:
        query_tokens = _tokenize(query)
        query_bigrams = _bigrams(query)
        ranked: list[tuple[int, SkillSpec]] = []
        for skill in self.discover():
            haystack = f"{skill.name} {skill.description} {skill.body[:400]}"
            haystack_tokens = _tokenize(haystack)
            haystack_bigrams = _bigrams(haystack)
            overlap = len(query_tokens & haystack_tokens)
            overlap += len(query_bigrams & haystack_bigrams)
            bonus = 2 if skill.name.replace("-", " ") in query.lower() else 0
            score = overlap + bonus
            if score > 0:
                ranked.append((score, skill))

        ranked.sort(key=lambda item: (-item[0], item[1].name))
        return [skill for _, skill in ranked[:limit]]

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
