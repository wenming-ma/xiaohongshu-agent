import importlib
import importlib.util
from pathlib import Path


def test_default_dub_script_points_to_repo_scripts_dir() -> None:
    video_dubbing_runner = importlib.import_module("src.agents.video_post.utils.video_dubbing_runner")
    expected_root = Path(__file__).resolve().parents[1]

    assert video_dubbing_runner.PROJECT_ROOT == expected_root
    assert video_dubbing_runner.DEFAULT_DUB_SCRIPT == expected_root / "scripts" / "dub_video.py"
    assert video_dubbing_runner.DEFAULT_DUB_SCRIPT.exists()


def test_dub_video_script_imports_video_post_entrypoint() -> None:
    video_dubbing_runner = importlib.import_module("src.agents.video_post.utils.video_dubbing_runner")
    video_dubbing = importlib.import_module("src.agents.video_post.utils.video_dubbing")
    script_path = video_dubbing_runner.DEFAULT_DUB_SCRIPT
    spec = importlib.util.spec_from_file_location("dub_video_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.dub_video is video_dubbing.dub_video
