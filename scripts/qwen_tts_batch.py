from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("SAFETENSORS_FAST_GPU", "1")


def _patch_safe_open() -> None:
    try:
        import safetensors
        from safetensors.torch import load_file
    except Exception:
        return

    class _DirectLoadSafeOpen:
        def __init__(self, filename, framework="pt", device="cpu"):
            self._data = load_file(filename, device=device)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def keys(self):
            return self._data.keys()

        def get_tensor(self, name):
            return self._data[name]

        def metadata(self):
            return {}

    safetensors.safe_open = _DirectLoadSafeOpen
    try:
        import transformers.modeling_utils as modeling_utils
    except Exception:
        return
    if hasattr(modeling_utils, "safe_open"):
        modeling_utils.safe_open = _DirectLoadSafeOpen


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch Qwen TTS synthesis")
    parser.add_argument("--request", required=True, help="Path to JSON request manifest")
    parser.add_argument("--response", required=True, help="Path to JSON response manifest")
    return parser.parse_args()


def _resolve_dtype(raw_dtype: str):
    import torch

    normalized = (raw_dtype or "").strip().lower()
    mapping = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "half": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    return mapping.get(normalized, torch.float16)


def _chunked(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(batch_size, 1)
    return [items[index:index + size] for index in range(0, len(items), size)]


def _load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_response(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_batch(payload: dict[str, Any]) -> dict[str, Any]:
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    _patch_safe_open()

    model_kwargs: dict[str, Any] = {
        "device_map": payload.get("device", "cuda:0"),
        "dtype": _resolve_dtype(str(payload.get("dtype", "float16"))),
    }
    attn_implementation = str(payload.get("attn_implementation", "")).strip()
    if attn_implementation:
        model_kwargs["attn_implementation"] = attn_implementation

    items = list(payload.get("items", []))
    batch_size = max(int(payload.get("batch_size", 1)), 1)
    model = Qwen3TTSModel.from_pretrained(str(payload["model_id"]), **model_kwargs)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for chunk in _chunked(items, batch_size):
        texts = [str(item["text"]) for item in chunk]
        speakers = [str(item["speaker"]) for item in chunk]
        languages = [str(item.get("language", "Auto")) for item in chunk]
        instructs = [str(item.get("instruct", "")) for item in chunk]

        try:
            wavs, sample_rate = model.generate_custom_voice(
                text=texts,
                speaker=speakers,
                language=languages,
                instruct=instructs,
            )
        except Exception as exc:
            for item in chunk:
                failures.append(
                    {
                        "segment_index": int(item["segment_index"]),
                        "error": str(exc),
                    }
                )
            continue

        for item, wav in zip(chunk, wavs):
            output_path = Path(str(item["output_path"]))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(output_path), wav, sample_rate)
            raw_duration = float(len(wav) / sample_rate) if sample_rate else 0.0
            results.append(
                {
                    "segment_index": int(item["segment_index"]),
                    "audio_path": str(output_path),
                    "raw_duration_seconds": raw_duration,
                    "speaker": str(item.get("speaker", "")),
                    "language": str(item.get("language", "")),
                }
            )

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "results": results,
        "failures": failures,
    }


def main() -> int:
    args = _parse_args()
    request_path = Path(args.request)
    response_path = Path(args.response)
    payload = _load_payload(request_path)
    result = _run_batch(payload)
    _write_response(response_path, result)
    print(
        json.dumps(
            {
                "segments": len(payload.get("items", [])),
                "successes": len(result["results"]),
                "failures": len(result["failures"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
