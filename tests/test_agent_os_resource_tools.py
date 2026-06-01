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


def test_resource_tools_list_local_files_for_user_provided_folder(tmp_path) -> None:
    image_path = tmp_path / "look.png"
    text_path = tmp_path / "notes.txt"
    image_path.write_bytes(b"png")
    text_path.write_text("hello", encoding="utf-8")
    tools = AgentOSResourceTools(skills_root=tmp_path / "skills", prompt_root=tmp_path / "prompt")

    files = tools.list_local_files(str(tmp_path), glob="*.png")

    assert files == [
        {
            "path": str(image_path.resolve()),
            "name": "look.png",
            "type": "file",
            "size": 3,
            "mime_type": "image/png",
        }
    ]


def test_resource_tools_read_local_text_file_with_size_cap(tmp_path) -> None:
    path = tmp_path / "brief.md"
    path.write_text("abcdef", encoding="utf-8")
    tools = AgentOSResourceTools(skills_root=tmp_path / "skills", prompt_root=tmp_path / "prompt")

    assert tools.read_local_text_file(str(path), max_chars=4) == "abcd"
