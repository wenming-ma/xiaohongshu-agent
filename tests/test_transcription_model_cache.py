import os
from pathlib import Path

from src.agents.shared.utils import transcription as transcription_module
from src.agents.video_post.utils import video_dubbing as video_dubbing_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_model_stub(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for filename in (
        "config.json",
        "model.bin",
        "preprocessor_config.json",
        "tokenizer.json",
    ):
        (model_dir / filename).write_text("stub", encoding="utf-8")


def test_cache_roots_resolve_from_repo_root() -> None:
    expected_hf_hub_cache = PROJECT_ROOT / ".cache" / "huggingface" / "hub"

    assert transcription_module.PROJECT_ROOT == PROJECT_ROOT
    assert transcription_module.HF_HUB_CACHE_DIR == expected_hf_hub_cache
    assert video_dubbing_module.PROJECT_ROOT == PROJECT_ROOT
    assert video_dubbing_module.HF_HUB_CACHE_DIR == expected_hf_hub_cache


def test_resolve_transcription_model_source_prefers_direct_model_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_root = tmp_path / "models--Systran--faster-whisper-large-v3"
    direct_model_dir = model_root / "faster-whisper-large-v3"
    _write_model_stub(direct_model_dir)

    monkeypatch.setattr(transcription_module, "HF_HUB_CACHE_DIR", tmp_path)
    monkeypatch.setattr(transcription_module, "LOCAL_TRANSCRIPTION_MODEL_ROOT", model_root)
    monkeypatch.setattr(transcription_module, "LOCAL_TRANSCRIPTION_MODEL_PATH", direct_model_dir)
    monkeypatch.setattr(
        transcription_module,
        "LOCAL_TRANSCRIPTION_MODEL_SNAPSHOTS_DIR",
        model_root / "snapshots",
    )

    model_source, download_root = transcription_module._resolve_transcription_model_source()

    assert model_source == str(direct_model_dir)
    assert download_root is None


def test_resolve_transcription_model_source_uses_latest_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_root = tmp_path / "models--Systran--faster-whisper-large-v3"
    snapshots_dir = model_root / "snapshots"
    older_snapshot = snapshots_dir / "older"
    newer_snapshot = snapshots_dir / "newer"
    _write_model_stub(older_snapshot)
    _write_model_stub(newer_snapshot)
    os.utime(older_snapshot, (1, 1))
    os.utime(newer_snapshot, (2, 2))

    monkeypatch.setattr(transcription_module, "HF_HUB_CACHE_DIR", tmp_path)
    monkeypatch.setattr(transcription_module, "LOCAL_TRANSCRIPTION_MODEL_ROOT", model_root)
    monkeypatch.setattr(
        transcription_module,
        "LOCAL_TRANSCRIPTION_MODEL_PATH",
        model_root / "faster-whisper-large-v3",
    )
    monkeypatch.setattr(
        transcription_module,
        "LOCAL_TRANSCRIPTION_MODEL_SNAPSHOTS_DIR",
        snapshots_dir,
    )

    model_source, download_root = transcription_module._resolve_transcription_model_source()

    assert model_source == str(newer_snapshot)
    assert download_root is None


def test_resolve_transcription_model_source_falls_back_to_repo_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_root = tmp_path / "models--Systran--faster-whisper-large-v3"

    monkeypatch.setattr(transcription_module, "HF_HUB_CACHE_DIR", tmp_path)
    monkeypatch.setattr(transcription_module, "LOCAL_TRANSCRIPTION_MODEL_ROOT", model_root)
    monkeypatch.setattr(
        transcription_module,
        "LOCAL_TRANSCRIPTION_MODEL_PATH",
        model_root / "faster-whisper-large-v3",
    )
    monkeypatch.setattr(
        transcription_module,
        "LOCAL_TRANSCRIPTION_MODEL_SNAPSHOTS_DIR",
        model_root / "snapshots",
    )

    model_source, download_root = transcription_module._resolve_transcription_model_source()

    assert model_source == transcription_module.TRANSCRIPTION_MODEL_REPO_ID
    assert download_root == str(tmp_path)
