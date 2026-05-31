from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTFIT_MODULE = "outfit" + "_post"
STYLED_MODULE = "styled" + "_image_post"


def _tracked_text_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            if path.suffix.lower() in {".py", ".md", ".txt", ".json", ".toml", ".ps1", ".example"}:
                files.append(path)
    return files


def test_removed_pipeline_and_master_entrypoints_are_absent() -> None:
    assert not (REPO_ROOT / "src" / "master").exists()
    assert not (REPO_ROOT / "src" / "core" / "pipeline_registry.py").exists()
    assert not (REPO_ROOT / "src" / "core" / "base_pipeline.py").exists()

    agent_pipeline_files = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src" / "agents").glob("*/pipeline.py")
    )
    assert agent_pipeline_files == []


def test_formal_agents_do_not_include_publish_phase_or_direct_publish_url() -> None:
    publish_dirs = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src" / "agents").glob("*/publish")
        if path.is_dir()
    )
    assert publish_dirs == []

    forbidden = [
        "creator.xiaohongshu.com/" + "publish",
        "XHS_" + "PUBLISH_URL",
        "publish" + "=True",
        "Pipeline" + "Registry",
        "Base" + "Pipeline",
    ]
    offenders: list[str] = []
    for path in _tracked_text_files("src", "tests", "workshop"):
        if path.name == "test_feishu_first_architecture_boundaries.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} contains {needle}")
    assert offenders == []


def test_formal_content_routes_exclude_outfit_and_styled_image_modules() -> None:
    assert not (REPO_ROOT / "src" / "agents" / OUTFIT_MODULE).exists()
    assert not (REPO_ROOT / "src" / "agents" / STYLED_MODULE).exists()


def test_feishu_orchestrator_is_promoted_to_formal_app_module() -> None:
    app_root = REPO_ROOT / "src" / "apps" / "feishu_orchestrator"
    assert app_root.is_dir()
    assert (app_root / "run.py").is_file()
    assert (app_root / "serve.py").is_file()

    assert not (REPO_ROOT / "workshop" / "image_post").exists()
    assert not (REPO_ROOT / "workshop" / "article_post").exists()
    assert not (REPO_ROOT / "workshop" / "video_post").exists()
    assert not (REPO_ROOT / "workshop" / STYLED_MODULE).exists()
    assert not (REPO_ROOT / "workshop" / OUTFIT_MODULE).exists()


def test_design_system_first_class_citizens_are_documented_and_present() -> None:
    agents_doc = (REPO_ROOT / "src" / "agents" / "AGENTS.md").read_text(encoding="utf-8")

    assert (REPO_ROOT / "src" / "agents").is_dir()
    assert (REPO_ROOT / ".agents" / "skills").is_dir()
    assert (REPO_ROOT / ".agents" / "prompt").is_dir()

    assert "three first-class citizens" in agents_doc
    assert "Atomic Agents" in agents_doc
    assert "Skill Protocol" in agents_doc
    assert "Prompt Templates" in agents_doc
    assert "Agent chooses" in agents_doc


def test_skill_protocol_is_not_branded_as_claude_style() -> None:
    offenders: list[str] = []
    for path in _tracked_text_files("src", "tests", ".agents"):
        if path.name == "test_feishu_first_architecture_boundaries.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Claude-style" in text or "Claude style" in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_prompt_library_is_categorized_and_substantial() -> None:
    prompt_root = REPO_ROOT / ".agents" / "prompt"
    expected_categories = {
        "image",
        "copy",
        "article",
        "video",
        "delivery",
        "research",
        "planning",
        "review",
        "meta",
    }
    categories = {
        path.name
        for path in prompt_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert expected_categories.issubset(categories)

    templates = [
        path
        for path in prompt_root.rglob("*.md")
        if path.name != "README.md"
    ]
    assert len(templates) >= 40

    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert "## Use When" in text
        assert "## Constraints" in text
        assert "## Prompt Template" in text

    readme = (prompt_root / "README.md").read_text(encoding="utf-8")
    assert "External Research Inputs" in readme
    assert "original project templates" in readme
    assert "do not copy" in readme.lower()


def test_image_prompt_library_is_primary_template_asset() -> None:
    image_root = REPO_ROOT / ".agents" / "prompt" / "image"
    expected_subcategories = {
        "cover",
        "fashion",
        "food",
        "knowledge",
        "product",
        "travel",
        "lifestyle",
        "style",
        "composition",
        "lighting",
        "reference",
    }
    subcategories = {
        path.name
        for path in image_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert expected_subcategories.issubset(subcategories)

    image_templates = [
        path
        for path in image_root.rglob("*.md")
        if path.name != "README.md"
    ]
    all_templates = [
        path
        for path in (REPO_ROOT / ".agents" / "prompt").rglob("*.md")
        if path.name != "README.md"
    ]
    assert len(image_templates) >= 30
    assert len(image_templates) >= len(all_templates) // 2
