import importlib.util
from pathlib import Path

from src.agents.video_post.utils.video_dubbing import dub_video
from src.agents.video_post.utils import video_dubbing_runner


def test_default_dub_script_points_to_repo_scripts_dir() -> None:
    expected_root = Path(__file__).resolve().parents[1]

    assert video_dubbing_runner.PROJECT_ROOT == expected_root
    assert video_dubbing_runner.DEFAULT_DUB_SCRIPT == expected_root / "scripts" / "dub_video.py"
    assert video_dubbing_runner.DEFAULT_DUB_SCRIPT.exists()


def test_dub_video_script_imports_video_post_entrypoint() -> None:
    script_path = video_dubbing_runner.DEFAULT_DUB_SCRIPT
    spec = importlib.util.spec_from_file_location("dub_video_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.dub_video is dub_video
