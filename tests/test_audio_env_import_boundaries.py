import importlib
import sys


def _clear_modules(*prefixes: str) -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            sys.modules.pop(name, None)


def test_shared_asr_import_does_not_eagerly_load_publish_tools() -> None:
    _clear_modules(
        "src.agents.shared",
        "src.agents.shared.body_inject",
        "src.agents.shared.playwright",
        "src.agents.shared.utils.asr.schemas",
    )

    importlib.import_module("src.agents.shared.utils.asr.model_sources")

    assert "src.agents.shared.body_inject" not in sys.modules
    assert "src.agents.shared.playwright" not in sys.modules
    assert "src.agents.shared.utils.asr.schemas" not in sys.modules


def test_create_fish_tts_provider_does_not_import_s2cpp() -> None:
    _clear_modules(
        "src.agents.video_post.utils.tts.registry",
        "src.agents.video_post.utils.tts.providers.s2cpp",
    )

    registry = importlib.import_module("src.agents.video_post.utils.tts.registry")
    provider = registry.create_tts_provider("fish")

    assert provider.provider_name == "fish"
    assert "src.agents.video_post.utils.tts.providers.s2cpp" not in sys.modules
