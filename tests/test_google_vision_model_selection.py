import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest


_VISION_MODULES = (
    "src.agents.image_post.research.tools",
)
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_fake_pydantic_ai() -> None:
    fake_module = sys.modules.get("pydantic_ai")
    if fake_module is None:
        fake_module = types.ModuleType("pydantic_ai")
        sys.modules["pydantic_ai"] = fake_module
    fake_module.__path__ = []

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _FakeTool:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _FakeBinaryContent:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _FakeRunContext:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        @classmethod
        def __class_getitem__(cls, _item):
            return cls

    fake_module.Agent = _FakeAgent
    fake_module.Tool = _FakeTool
    fake_module.BinaryContent = _FakeBinaryContent
    fake_module.RunContext = _FakeRunContext

    usage_module = types.ModuleType("pydantic_ai.usage")

    class _FakeUsageLimits:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    usage_module.UsageLimits = _FakeUsageLimits
    sys.modules["pydantic_ai.usage"] = usage_module


def _ensure_fake_logfire() -> None:
    if "logfire" in sys.modules:
        return

    fake_module = types.ModuleType("logfire")

    class _FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_attribute(self, *args, **kwargs):
            return None

    fake_module.span = lambda *args, **kwargs: _FakeSpan()
    fake_module.info = lambda *args, **kwargs: None
    fake_module.warn = lambda *args, **kwargs: None
    fake_module.error = lambda *args, **kwargs: None
    fake_module.configure = lambda *args, **kwargs: None
    fake_module.instrument_pydantic_ai = lambda *args, **kwargs: None
    sys.modules["logfire"] = fake_module


def _ensure_package_chain(module_name: str) -> None:
    parts = module_name.split(".")
    for idx in range(1, len(parts)):
        package_name = ".".join(parts[:idx])
        if package_name in sys.modules:
            continue
        package_module = types.ModuleType(package_name)
        package_module.__path__ = [str(_REPO_ROOT.joinpath(*parts[:idx]))]
        sys.modules[package_name] = package_module


def _ensure_fake_providers_module() -> None:
    if "src.utils" not in sys.modules:
        utils_module = types.ModuleType("src.utils")
        utils_module.__path__ = [str(_REPO_ROOT / "src" / "utils")]
        sys.modules["src.utils"] = utils_module

    providers_module = sys.modules.get("src.utils.providers")
    if providers_module is None:
        providers_module = types.ModuleType("src.utils.providers")
        sys.modules["src.utils.providers"] = providers_module

    class _DummySub2APIVisionClient:
        pass

    class _DummySub2APIImageClient:
        pass

    class _DummyVertexAIVisionClient:
        pass

    class _DummyVertexAIImageClient:
        pass

    providers_module.Sub2APIVisionClient = _DummySub2APIVisionClient
    providers_module.Sub2APIImageClient = _DummySub2APIImageClient
    providers_module.VertexAIVisionClient = _DummyVertexAIVisionClient
    providers_module.VertexAIImageClient = _DummyVertexAIImageClient
    providers_module.get_text_model = lambda *args, **kwargs: "text-model"
    providers_module.get_openai_model = lambda *args, **kwargs: "openai-model"
    providers_module.get_google_model = lambda *args, **kwargs: "google-model"


def _load_module(module_name: str):
    _ensure_fake_pydantic_ai()
    _ensure_fake_logfire()
    _ensure_package_chain(module_name)
    _ensure_fake_providers_module()
    module_path = _REPO_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("module_name", _VISION_MODULES)
def test_image_reader_agents_use_sub2api_vision_client(monkeypatch, module_name: str) -> None:
    module = _load_module(module_name)
    vision_clients: list[object] = []

    class _FakeVisionClient:
        def __init__(self, *args, **kwargs):
            vision_clients.append(self)

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            self.model = kwargs.get("model")

    monkeypatch.setattr(module, "Agent", _FakeAgent)
    monkeypatch.setattr(module, "VertexAIVisionClient", _FakeVisionClient, raising=False)
    monkeypatch.setattr(
        module,
        "Sub2APIVisionClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use Sub2APIVisionClient")),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "get_google_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use get_google_model")),
        raising=False,
    )

    image_reader = module.ImageReaderAgent()
    post_reader = module.PostImageReaderAgent(mcp_server=object())

    assert len(vision_clients) == 2
    assert getattr(image_reader, "_vision_client", None) is vision_clients[0]
    assert getattr(post_reader, "_vision_client", None) is vision_clients[1]
