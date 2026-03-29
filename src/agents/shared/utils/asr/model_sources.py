from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[5]
PROJECT_CACHE = PROJECT_ROOT / ".cache"


def _expand_path(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser()


def _resolve_hf_home_dir() -> Path:
    env_hf_home = _expand_path(os.getenv("HF_HOME"))
    if env_hf_home is not None:
        return env_hf_home

    env_hf_hub_cache = _expand_path(os.getenv("HF_HUB_CACHE"))
    if env_hf_hub_cache is not None:
        return env_hf_hub_cache.parent

    try:
        import huggingface_hub.constants as hf_constants

        hf_home = _expand_path(getattr(hf_constants, "HF_HOME", None))
        if hf_home is not None:
            return hf_home
        hf_hub_cache = _expand_path(getattr(hf_constants, "HF_HUB_CACHE", None))
        if hf_hub_cache is not None:
            return hf_hub_cache.parent
    except Exception:
        pass

    return Path.home() / ".cache" / "huggingface"


def _resolve_hf_hub_cache_dir() -> Path:
    env_hf_hub_cache = _expand_path(os.getenv("HF_HUB_CACHE"))
    if env_hf_hub_cache is not None:
        return env_hf_hub_cache

    try:
        import huggingface_hub.constants as hf_constants

        hf_hub_cache = _expand_path(getattr(hf_constants, "HF_HUB_CACHE", None))
        if hf_hub_cache is not None:
            return hf_hub_cache
    except Exception:
        pass

    return _resolve_hf_home_dir() / "hub"


HF_HOME_DIR = _resolve_hf_home_dir()
HF_HUB_CACHE_DIR = _resolve_hf_hub_cache_dir()


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

QWEN_ASR_MODEL_SPEC = ModelSpec(
    provider_name="qwen",
    repo_id="Qwen/Qwen3-ASR-1.7B",
    cache_root_name="models--Qwen--Qwen3-ASR-1.7B",
    required_files=("config.json",),
)

QWEN_FORCED_ALIGNER_MODEL_SPEC = ModelSpec(
    provider_name="qwen_forced_aligner",
    repo_id="Qwen/Qwen3-ForcedAligner-0.6B",
    cache_root_name="models--Qwen--Qwen3-ForcedAligner-0.6B",
    required_files=("config.json",),
)


def prepare_hf_cache_env() -> None:
    HF_HUB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def is_hf_offline_mode() -> bool:
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        raw = os.getenv(key, "").strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
    return False


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
