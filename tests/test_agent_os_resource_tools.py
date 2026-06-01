from __future__ import annotations

from src.agent_os.resource_tools import AgentOSResourceTools


def test_resource_tools_list_and_read_skills(tmp_path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\n---\n# Demo\nUse for demos.",
        encoding="utf-8",
    )
    tools = AgentOSResourceTools(
        skills_root=tmp_path / "skills",
        prompt_root=tmp_path / "prompt",
    )

    skills = tools.list_skills()
    body = tools.read_skill("demo")

    assert skills == [{"name": "demo", "path": str(skill_dir / "SKILL.md")}]
    assert "# Demo" in body


def test_resource_tools_search_prompt_templates_by_content_not_filename_trigger(tmp_path) -> None:
    prompt_root = tmp_path / "prompt"
    (prompt_root / "image").mkdir(parents=True)
    template = prompt_root / "image" / "editorial.md"
    template.write_text(
        "## Use When\nUse for cinematic product photography.\n",
        encoding="utf-8",
    )
    tools = AgentOSResourceTools(skills_root=tmp_path / "skills", prompt_root=prompt_root)

    results = tools.search_prompt_templates("cinematic product")

    assert results == [{"path": str(template), "score": 2}]
    assert "cinematic product photography" in tools.read_prompt_template(str(template))
