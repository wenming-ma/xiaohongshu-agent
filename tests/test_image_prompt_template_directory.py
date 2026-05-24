import asyncio
import json
from pathlib import Path

from src.agents.image_post.image.template_tools import PromptTemplateDirectoryToolset


def test_template_directory_tools_list_roots_and_do_not_dump_file_contents(tmp_path: Path) -> None:
    repo = tmp_path / "awesome-prompts"
    repo.mkdir()
    (repo / "README.md").write_text("# Awesome prompts\nsocial media prompt", encoding="utf-8")
    (repo / "prompt.md").write_text("full prompt body should not appear in root listing", encoding="utf-8")

    tools = PromptTemplateDirectoryToolset(tmp_path)

    payload = json.loads(asyncio.run(tools.list_template_roots()))

    assert payload["root"] == str(tmp_path)
    assert payload["sources"][0]["name"] == "awesome-prompts"
    assert "full prompt body" not in json.dumps(payload, ensure_ascii=False)


def test_template_directory_tools_search_and_read_selected_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "food.md").write_text("Food photography prompt with steam and table styling", encoding="utf-8")
    (repo / "fashion.md").write_text("Fashion editorial prompt", encoding="utf-8")

    tools = PromptTemplateDirectoryToolset(tmp_path)

    search_payload = json.loads(asyncio.run(tools.search_templates("steam table", max_results=5)))
    read_payload = json.loads(asyncio.run(tools.read_template_file("repo/food.md", max_chars=20)))

    assert search_payload["results"][0]["path"] == "repo/food.md"
    assert "steam" in search_payload["results"][0]["snippet"]
    assert read_payload["path"] == "repo/food.md"
    assert read_payload["truncated"] is True
    assert read_payload["content"] == "Food photography pro"


def test_template_directory_tools_reject_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-template.txt"
    outside.write_text("secret", encoding="utf-8")
    tools = PromptTemplateDirectoryToolset(tmp_path)

    payload = json.loads(asyncio.run(tools.read_template_file("../outside-template.txt")))

    assert "error" in payload
    assert "outside template root" in payload["error"]
