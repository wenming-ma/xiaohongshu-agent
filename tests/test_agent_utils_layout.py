from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
AGENTS_ROOT = SRC_ROOT / "agents"
SHARED_UTILS = SRC_ROOT / "utils"

EXPECTED_AGENT_UTILS = [
    AGENTS_ROOT / "article_post" / "utils",
    AGENTS_ROOT / "image_post" / "utils",
    AGENTS_ROOT / "shared" / "utils",
    AGENTS_ROOT / "video_post" / "utils",
]

REMOVED_SHARED_BUSINESS_FILES = [
    "download_manager.py",
    "image_compression.py",
    "image_sanitizer.py",
    "navigate_tracker.py",
    "playwright_artifacts.py",
    "transcription.py",
    "tts_tags.py",
    "video_dubbing.py",
    "video_dubbing_runner.py",
    "video_frames.py",
    "watermark_remover.py",
]


def test_every_agent_family_has_a_dedicated_utils_package() -> None:
    for path in EXPECTED_AGENT_UTILS:
        assert path.is_dir(), f"missing utils package: {path}"
        assert (path / "__init__.py").exists(), f"missing __init__.py: {path}"


def test_phase_directories_no_longer_define_utils_py_files() -> None:
    leftover = sorted(
        str(path.relative_to(PROJECT_ROOT))
        for path in AGENTS_ROOT.rglob("utils.py")
    )
    assert leftover == []


def test_src_utils_keeps_only_infra_modules() -> None:
    for filename in REMOVED_SHARED_BUSINESS_FILES:
        assert not (SHARED_UTILS / filename).exists(), f"{filename} should not stay in src/utils"
