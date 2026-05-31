from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from src.config.settings import PathConfig

from .skills import SkillSpec


class StylePromptRef(BaseModel):
    source: str
    title: str = ""
    excerpt: str = ""
    tags: list[str] = Field(default_factory=list)


class StyleContext(BaseModel):
    user_constraints: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    prompt_refs: list[StylePromptRef] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        request: Any,
        *,
        matched_skills: Sequence[SkillSpec] = (),
    ) -> "StyleContext":
        user_constraints = _dedupe(getattr(request, "style_constraints", []) or [])
        hard_constraints = _derive_hard_constraints(request, user_constraints)
        negative_constraints = _derive_negative_constraints(user_constraints)
        query = _build_prompt_library_query(request, user_constraints)
        prompt_refs: list[StylePromptRef] = []
        for skill in matched_skills:
            prompt_refs.extend(_load_skill_prompt_refs(skill))
        prompt_refs.extend(_load_prompt_library_refs(query))

        return cls(
            user_constraints=user_constraints,
            matched_skills=[skill.name for skill in matched_skills],
            prompt_refs=prompt_refs,
            hard_constraints=hard_constraints,
            negative_constraints=negative_constraints,
            trace={
                "source": "conversation_request_and_project_skills",
                "skill_count": len(matched_skills),
                "prompt_ref_count": len(prompt_refs),
                "query": query,
            },
        )

    def to_prompt_section(self) -> str:
        lines = ["## 风格上下文"]
        if self.user_constraints:
            lines.append("用户明确风格约束：")
            lines.extend(f"- {item}" for item in self.user_constraints)
        if self.matched_skills:
            lines.append("匹配到的 Skill：")
            lines.extend(f"- {name}" for name in self.matched_skills)
        if self.hard_constraints:
            lines.append("硬性视觉约束：")
            lines.extend(f"- {item}" for item in self.hard_constraints)
        if self.negative_constraints:
            lines.append("禁用项：")
            lines.extend(f"- {item}" for item in self.negative_constraints)
        if self.prompt_refs:
            lines.append("仓库版本化风格参考：")
            for ref in self.prompt_refs:
                lines.append(f"- 来源：{ref.source}")
                if ref.title:
                    lines.append(f"  标题：{ref.title}")
                if ref.excerpt:
                    lines.append(f"  摘要：{ref.excerpt}")
        return "\n".join(lines)

    def metadata(self) -> dict[str, Any]:
        return {
            "user_constraints": list(self.user_constraints),
            "matched_skills": list(self.matched_skills),
            "prompt_ref_sources": [ref.source for ref in self.prompt_refs],
            "hard_constraints": list(self.hard_constraints),
            "negative_constraints": list(self.negative_constraints),
        }


def _dedupe(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _derive_hard_constraints(request: Any, user_constraints: Sequence[str]) -> list[str]:
    constraints = list(user_constraints)
    image_count = getattr(request, "image_count", None)
    if image_count:
        constraints.append(f"图片数量：{image_count} 张")
    return _dedupe(constraints)


def _derive_negative_constraints(user_constraints: Sequence[str]) -> list[str]:
    negatives = [
        "不要生成登录弹窗、应用界面、app screenshots、工具报错、研究限制说明或 session 状态卡片",
        "不要把研究诊断信息、内部审核意见、提示词模板说明画进图片",
    ]
    joined = " ".join(user_constraints)
    if any(marker in joined for marker in ("不要人物", "无人物", "不需要人物", "no people")):
        negatives.append("不要人物、模特、人台或拟人化身体部位")
    return _dedupe(negatives)


def _build_prompt_library_query(request: Any, user_constraints: Sequence[str]) -> str:
    parts = [
        getattr(request, "topic", ""),
        getattr(request, "audience", ""),
        getattr(request, "message", ""),
        *user_constraints,
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _load_prompt_library_refs(query: str, *, limit: int = 3) -> list[StylePromptRef]:
    root = Path(os.getenv("PROMPT_TEMPLATE_ROOT", PathConfig.PROMPT_TEMPLATE_ROOT))
    if not root.exists() or not root.is_dir():
        return []

    scored: list[tuple[int, Path]] = []
    for source_file in sorted(root.glob("*.md")):
        if source_file.name.lower() == "readme.md" or not source_file.is_file():
            continue
        text = source_file.read_text(encoding="utf-8", errors="ignore")
        score = _score_text_for_query(text=f"{source_file.stem} {text}", query=query)
        if score > 0:
            scored.append((score, source_file))

    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [
        _build_prompt_ref(source_file, tags=["prompt-library"])
        for _, source_file in scored[:limit]
    ]


def _load_skill_prompt_refs(skill: SkillSpec) -> list[StylePromptRef]:
    refs_dir = skill.path / "references"
    source_files = sorted(refs_dir.glob("*.md")) if refs_dir.exists() else []
    if not source_files:
        source_files = [skill.path / "SKILL.md"]

    refs: list[StylePromptRef] = []
    for source_file in source_files:
        if not source_file.exists() or not source_file.is_file():
            continue
        refs.append(_build_prompt_ref(source_file, title_fallback=skill.name, tags=[skill.name]))
    return refs


def _build_prompt_ref(
    source_file: Path,
    *,
    title_fallback: str = "",
    tags: Sequence[str] = (),
) -> StylePromptRef:
    text = source_file.read_text(encoding="utf-8", errors="ignore")
    return StylePromptRef(
        source=_normalize_source(source_file),
        title=_extract_title(text) or title_fallback,
        excerpt=_compact_excerpt(text),
        tags=list(tags),
    )


def _score_text_for_query(*, text: str, query: str) -> int:
    query_terms = _terms(query)
    if not query_terms:
        return 0
    lowered = text.lower()
    score = 0
    for term in query_terms:
        if term in lowered:
            score += 3 if len(term) > 2 else 1
    return score


def _terms(text: str) -> list[str]:
    import re

    raw_terms = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text.lower())
    terms: list[str] = []
    for raw in raw_terms:
        if len(raw) <= 1:
            continue
        terms.append(raw)
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw) and len(raw) > 2:
            terms.extend(raw[idx : idx + 2] for idx in range(len(raw) - 1))
    return _dedupe(terms)


def _normalize_source(path: Path) -> str:
    return path.resolve().as_posix()


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _compact_excerpt(text: str, *, max_chars: int = 800) -> str:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("---")
    ]
    excerpt = " ".join(lines)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 1].rstrip() + "…"
