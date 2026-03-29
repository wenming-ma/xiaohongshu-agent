from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[5]
PROJECT_CACHE = PROJECT_ROOT / ".cache"
HF_HOME_DIR = PROJECT_CACHE / "huggingface"
HF_HUB_CACHE_DIR = HF_HOME_DIR / "hub"


@dataclass(frozen=True)
class ModelSpec:
    provider_name: str
    repo_id: str
    cache_root_name: str
    required_files: tuple[str, ...]
    direct_model_dir_name: str | None = None


FASTER_WHISPER_MODEL_SPEC = ModelSpec(
    provider_name="faster_whisper",
    repo_id="Systran/faster-whisper-large-v3",
    cache_root_name="models--Systran--faster-whisper-large-v3",
    required_files=("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json"),
    direct_model_dir_name="faster-whisper-large-v3",
)

COHERE_ASR_MODEL_SPEC = ModelSpec(
    provider_name="cohere",
    repo_id="CohereLabs/cohere-transcribe-03-2026",
    cache_root_name="models--CohereLabs--cohere-transcribe-03-2026",
    required_files=("config.json", "model.safetensors", "preprocessor_config.json", "tokenizer.json"),
)


def prepare_hf_cache_env() -> None:
    HF_HUB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_env = {
        "XDG_CACHE_HOME": str(PROJECT_CACHE),
        "HF_HOME": str(HF_HOME_DIR),
        "HF_HUB_CACHE": str(HF_HUB_CACHE_DIR),
        "TRANSFORMERS_CACHE": str(HF_HUB_CACHE_DIR),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
    }
    for key, value in cache_env.items():
        os.environ[key] = value

    try:
        import huggingface_hub.constants as hf_constants

        if hasattr(hf_constants, "HF_HOME"):
            hf_constants.HF_HOME = str(HF_HOME_DIR)
        if hasattr(hf_constants, "HF_HUB_CACHE"):
            hf_constants.HF_HUB_CACHE = str(HF_HUB_CACHE_DIR)
    except Exception:
        pass


def prepare_cuda_library_path() -> None:
    cublas_bin = PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
    if not cublas_bin.exists():
        return

    current_path = os.environ.get("PATH", "")
    current_entries = current_path.split(os.pathsep) if current_path else []
    if str(cublas_bin) in current_entries:
        return
    os.environ["PATH"] = str(cublas_bin) + os.pathsep + current_path


def _is_model_dir(path: Path, required_files: tuple[str, ...]) -> bool:
    return path.is_dir() and all((path / filename).exists() for filename in required_files)


def resolve_model_source_from_root(
    model_root: Path,
    *,
    repo_id: str,
    required_files: tuple[str, ...],
    direct_model_dir_name: str | None = None,
    cache_dir: Path = HF_HUB_CACHE_DIR,
) -> tuple[str, str | None]:
    if _is_model_dir(model_root, required_files):
        return str(model_root), None

    if direct_model_dir_name:
        direct_model_dir = model_root / direct_model_dir_name
        if _is_model_dir(direct_model_dir, required_files):
            return str(direct_model_dir), None

    snapshots_dir = model_root / "snapshots"
    if snapshots_dir.is_dir():
        snapshot_dirs = sorted(
            (
                path
                for path in snapshots_dir.iterdir()
                if _is_model_dir(path, required_files)
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if snapshot_dirs:
            return str(snapshot_dirs[0]), None

    return repo_id, str(cache_dir)


def resolve_model_source(spec: ModelSpec) -> tuple[str, str | None]:
    return resolve_model_source_from_root(
        HF_HUB_CACHE_DIR / spec.cache_root_name,
        repo_id=spec.repo_id,
        required_files=spec.required_files,
        direct_model_dir_name=spec.direct_model_dir_name,
        cache_dir=HF_HUB_CACHE_DIR,
    )
