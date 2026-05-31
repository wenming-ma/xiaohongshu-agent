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
