import importlib.util
import sys
from pathlib import Path


def _load_dub_video_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dub_video.py"
    spec = importlib.util.spec_from_file_location("dub_video_script_cli", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dub_video_cli_accepts_qwen_provider(monkeypatch) -> None:
    module = _load_dub_video_script()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dub_video.py",
            "--video",
            "input.mp4",
            "--srt",
            "input.srt",
            "--output",
            "output.mp4",
            "--tts-provider",
            "qwen",
        ],
    )

    args = module.parse_args()

    assert args.tts_provider == "qwen"
