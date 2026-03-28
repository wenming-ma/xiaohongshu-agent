from pathlib import Path

from src.agents.video_post.utils import video_dubbing_runner


def test_default_dub_script_points_to_repo_scripts_dir() -> None:
    expected_root = Path(__file__).resolve().parents[1]

    assert video_dubbing_runner.PROJECT_ROOT == expected_root
    assert video_dubbing_runner.DEFAULT_DUB_SCRIPT == expected_root / "scripts" / "dub_video.py"
    assert video_dubbing_runner.DEFAULT_DUB_SCRIPT.exists()
