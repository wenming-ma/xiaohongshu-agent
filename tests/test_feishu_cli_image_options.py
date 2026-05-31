from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(module_path: str, module_name: str):
    path = Path(__file__).resolve().parents[1].joinpath(*module_path.split("/"))
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_once_module_does_not_import_settings_before_dotenv() -> None:
    for name in [
        "src.config.settings",
        "src.orchestration.run_options",
        "src.apps.feishu_orchestrator.cli_image_options",
    ]:
        sys.modules.pop(name, None)

    _load_module(
        "src/apps/feishu_orchestrator/run_once_image_post.py",
        "run_once_image_post_import_order_test",
    )

    assert "src.config.settings" not in sys.modules


def test_run_once_image_post_cli_accepts_reference_images_and_image_runtime_options(monkeypatch) -> None:
    module = _load_module(
        "src/apps/feishu_orchestrator/run_once_image_post.py",
        "run_once_image_post_for_cli_test",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_once_image_post",
            "--topic",
            "参考图穿搭",
            "--audience",
            "通勤女生",
            "--reference-image",
            "C:/refs/look-a.png",
            "--reference-image",
            "C:/refs/look-b.png",
            "--image-reference-mode",
            "none",
            "--disable-keyword-prompt-expansion",
        ],
    )

    args = module.parse_args()
    options = module.build_image_post_run_options_from_args(args)

    assert args.reference_image == ["C:/refs/look-a.png", "C:/refs/look-b.png"]
    assert options.image.reference_mode == "none"
    assert options.image.keyword_prompt_expansion is False


def test_feishu_run_cli_accepts_call_time_image_request_and_runtime_options(monkeypatch) -> None:
    module = _load_module(
        "src/apps/feishu_orchestrator/run.py",
        "feishu_orchestrator_run_for_cli_options_test",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "feishu_orchestrator_run",
            "--topic",
            "登山穿搭",
            "--audience",
            "户外新手",
            "--image-count",
            "5",
            "--reference-image",
            "C:/refs/hiking.png",
            "--research-min-posts",
            "6",
            "--research-validation-retries",
            "2",
            "--image-max-retries",
            "3",
            "--image-size",
            "4K",
            "--image-aspect-ratio",
            "3:4",
        ],
    )

    args = module.parse_args()
    options = module.build_image_post_run_options_from_args(args)

    assert args.image_count == 5
    assert args.reference_image == ["C:/refs/hiking.png"]
    assert options.research.min_posts_researched == 6
    assert options.research.validation_max_retries == 2
    assert options.image.max_retries == 3
    assert options.image.image_size == "4K"
    assert options.image.aspect_ratio == "3:4"
