import importlib
from pathlib import Path

import huggingface_hub.constants as hf_constants

from src.agents.shared.utils.asr import model_sources as model_sources_module
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


def test_cache_roots_resolve_from_huggingface_defaults() -> None:
    expected_hf_hub_cache = Path(hf_constants.HF_HUB_CACHE)

    assert model_sources_module.PROJECT_ROOT == PROJECT_ROOT
    assert model_sources_module.HF_HUB_CACHE_DIR == expected_hf_hub_cache
    assert video_dubbing_module.PROJECT_ROOT == PROJECT_ROOT
    assert video_dubbing_module.HF_HUB_CACHE_DIR == expected_hf_hub_cache


def test_model_sources_respect_explicit_hf_cache_env(monkeypatch, tmp_path: Path) -> None:
    with monkeypatch.context() as env_ctx:
        env_ctx.setenv("HF_HOME", str(tmp_path / "hf-home"))
        env_ctx.setenv("HF_HUB_CACHE", str(tmp_path / "hf-home" / "hub"))

        reloaded = importlib.reload(model_sources_module)
        assert reloaded.HF_HOME_DIR == tmp_path / "hf-home"
        assert reloaded.HF_HUB_CACHE_DIR == tmp_path / "hf-home" / "hub"

    importlib.reload(model_sources_module)
    importlib.reload(video_dubbing_module)

def test_resolve_model_source_from_root_prefers_direct_model_dir(tmp_path: Path) -> None:
    model_root = tmp_path / "models--Systran--faster-whisper-large-v3"
    direct_model_dir = model_root / model_sources_module.FASTER_WHISPER_MODEL_SPEC.direct_model_dir_name
    _write_model_stub(direct_model_dir)

    model_source, download_root = model_sources_module.resolve_model_source_from_root(
        model_root,
        repo_id=model_sources_module.FASTER_WHISPER_MODEL_SPEC.repo_id,
        required_files=model_sources_module.FASTER_WHISPER_MODEL_SPEC.required_files,
        direct_model_dir_name=direct_model_dir.name,
        cache_dir=tmp_path,
    )

    assert model_source == str(direct_model_dir)
    assert download_root is None


def test_resolve_model_source_from_root_uses_latest_snapshot(tmp_path: Path) -> None:
    import os

    model_root = tmp_path / "models--Systran--faster-whisper-large-v3"
    snapshots_dir = model_root / "snapshots"
    older_snapshot = snapshots_dir / "older"
    newer_snapshot = snapshots_dir / "newer"
    _write_model_stub(older_snapshot)
    _write_model_stub(newer_snapshot)
    os.utime(older_snapshot, (1, 1))
    os.utime(newer_snapshot, (2, 2))

    model_source, download_root = model_sources_module.resolve_model_source_from_root(
        model_root,
        repo_id=model_sources_module.FASTER_WHISPER_MODEL_SPEC.repo_id,
        required_files=model_sources_module.FASTER_WHISPER_MODEL_SPEC.required_files,
        direct_model_dir_name=model_sources_module.FASTER_WHISPER_MODEL_SPEC.direct_model_dir_name,
        cache_dir=tmp_path,
    )

    assert model_source == str(newer_snapshot)
    assert download_root is None


def test_resolve_model_source_from_root_falls_back_to_repo_id(tmp_path: Path) -> None:
    model_root = tmp_path / "models--Systran--faster-whisper-large-v3"

    model_source, download_root = model_sources_module.resolve_model_source_from_root(
        model_root,
        repo_id=model_sources_module.FASTER_WHISPER_MODEL_SPEC.repo_id,
        required_files=model_sources_module.FASTER_WHISPER_MODEL_SPEC.required_files,
        direct_model_dir_name=model_sources_module.FASTER_WHISPER_MODEL_SPEC.direct_model_dir_name,
        cache_dir=tmp_path,
    )

    assert model_source == model_sources_module.FASTER_WHISPER_MODEL_SPEC.repo_id
    assert download_root == str(tmp_path)
