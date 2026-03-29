from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASR_ROOT = PROJECT_ROOT / "src" / "agents" / "shared" / "utils" / "asr"
SRC_ROOT = PROJECT_ROOT / "src"


def test_shared_asr_does_not_import_video_post_schemas() -> None:
    for path in ASR_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "src.agents.video_post.schemas" not in text, str(path.relative_to(PROJECT_ROOT))


def test_repo_does_not_use_legacy_transcription_module() -> None:
    assert not (SRC_ROOT / "agents" / "shared" / "utils" / "transcription.py").exists()

    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "shared.utils.transcription" not in text, str(path.relative_to(PROJECT_ROOT))
