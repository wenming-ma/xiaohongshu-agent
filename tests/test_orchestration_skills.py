from __future__ import annotations

from pathlib import Path

from src.orchestration.skills import ProjectSkillRegistry


def _write_skill(root: Path, name: str, description: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def test_skill_registry_discovers_project_skills_without_runtime_matching(tmp_path: Path) -> None:
    skills_root = tmp_path / ".agents" / "skills"
    _write_skill(
        skills_root,
        "solid-background-single-look",
        "纯色背景、每张图只展示一套穿搭。用于穿搭图文和服饰展示。",
        "# Solid background\n\nKeep the background flat and isolate a single outfit per image.",
    )
    _write_skill(
        skills_root,
        "knowledge-roundup-image-post",
        "知识总结型图文，适合做信息整理和步骤拆解。",
        "# Knowledge roundup\n\nTurn research into clean, structured image slides.",
    )

    registry = ProjectSkillRegistry(skills_root=skills_root)
    skills = registry.discover()

    assert [skill.name for skill in skills] == [
        "knowledge-roundup-image-post",
        "solid-background-single-look",
    ]

    assert not hasattr(registry, "match")
