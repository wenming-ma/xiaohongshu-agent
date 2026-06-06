import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest


_IMAGE_AGENT_MODULES = (
    (
        "src.agents.image_post.image.agent",
        "ImageAgent",
        {"model": "gemini-3-pro-image-preview", "image_size": "2K", "aspect_ratio": "3:4"},
    ),
    ("src.agents.article_post.image.agent", "ImageAgent", {"aspect_ratio": "16:9"}),
    ("src.agents.video_post.cover.agent", "CoverAgent", {"aspect_ratio": "16:9"}),
)

_VALIDATOR_MODULES = (
    "src.agents.image_post.image.validator",
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

        def system_prompt(self, fn):
            return fn

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

    usage_module = sys.modules.get("pydantic_ai.usage")
    if usage_module is None:
        usage_module = types.ModuleType("pydantic_ai.usage")

    class _FakeUsageLimits:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    usage_module.UsageLimits = _FakeUsageLimits
    sys.modules["pydantic_ai.usage"] = usage_module

    messages_module = sys.modules.get("pydantic_ai.messages")
    if messages_module is None:
        messages_module = types.ModuleType("pydantic_ai.messages")

    class _FakeModelMessage:
        pass

    messages_module.ModelMessage = _FakeModelMessage
    sys.modules["pydantic_ai.messages"] = messages_module


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

    class _DummySub2APIImageClient:
        pass

    class _DummySub2APIVisionClient:
        pass

    class _DummyVertexAIImageClient:
        pass

    class _DummyVertexAIVisionClient:
        pass

    providers_module.Sub2APIImageClient = _DummySub2APIImageClient
    providers_module.Sub2APIVisionClient = _DummySub2APIVisionClient
    providers_module.VertexAIImageClient = _DummyVertexAIImageClient
    providers_module.VertexAIVisionClient = _DummyVertexAIVisionClient
    providers_module.get_text_model = lambda *args, **kwargs: "text-model"
    providers_module.get_openai_model = lambda *args, **kwargs: "openai-model"
    providers_module.get_google_model = lambda *args, **kwargs: "google-model"


def _ensure_fake_agent_support_modules() -> None:
    template_module_name = "src.agents.image_post.image.template_agent"
    if template_module_name not in sys.modules:
        template_module = types.ModuleType(template_module_name)

        class _FakeImagePromptTemplateAgent:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        template_module.ImagePromptTemplateAgent = _FakeImagePromptTemplateAgent
        template_module.format_template_guidance = lambda *args, **kwargs: ""
        sys.modules[template_module_name] = template_module

    for module_name in (
        "src.agents.image_post.utils.image",
    ):
        if module_name in sys.modules:
            continue
        image_utils_module = types.ModuleType(module_name)
        image_utils_module.build_compact_items = lambda *args, **kwargs: []
        image_utils_module.calculate_grouping_params = lambda *args, **kwargs: (1, 1, 1)
        image_utils_module.groups_to_image_specs = lambda *args, **kwargs: []
        image_utils_module.normalize_group_assignments = lambda groups, **kwargs: groups
        image_utils_module.run_grouping_with_review = lambda *args, **kwargs: []
        sys.modules[module_name] = image_utils_module


def _load_module(module_name: str):
    _ensure_fake_pydantic_ai()
    _ensure_fake_logfire()
    _ensure_package_chain(module_name)
    _ensure_fake_providers_module()
    _ensure_fake_agent_support_modules()
    module_path = _REPO_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("module_name", "class_name", "expected_kwargs"), _IMAGE_AGENT_MODULES)
def test_visual_generation_agents_use_sub2api_image_client(
    monkeypatch,
    module_name: str,
    class_name: str,
    expected_kwargs: dict[str, str],
) -> None:
    module = _load_module(module_name)
    client_kwargs: list[dict[str, object]] = []

    class _FakeVertexAIImageClient:
        def __init__(self, *args, **kwargs):
            client_kwargs.append(kwargs)

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def system_prompt(self, fn):
            return fn

    monkeypatch.setattr(module, "VertexAIImageClient", _FakeVertexAIImageClient, raising=False)
    monkeypatch.setattr(
        module,
        "Sub2APIImageClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use Sub2APIImageClient")),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "GeminiImageClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use GeminiImageClient")),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "GeminiWebImageClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use GeminiWebImageClient")),
        raising=False,
    )
    monkeypatch.setattr(module, "Agent", _FakeAgent)
    monkeypatch.setattr(module, "get_text_model", lambda *args, **kwargs: "text-model", raising=False)
    monkeypatch.setattr(module, "get_openai_model", lambda *args, **kwargs: "openai-model", raising=False)
    monkeypatch.setattr(module, "ImageQualityValidator", lambda *args, **kwargs: object(), raising=False)

    agent = getattr(module, class_name)()

    assert len(client_kwargs) == 1
    assert client_kwargs[0] == expected_kwargs
    assert getattr(agent, "image_client", None) is not None
    assert not hasattr(agent, "web_image_client")


def test_image_post_grouping_agents_use_default_text_model(monkeypatch) -> None:
    module = _load_module("src.agents.image_post.image.agent")
    agent_models: list[object] = []

    class _FakeVertexAIImageClient:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            agent_models.append(kwargs.get("model"))
            self.kwargs = kwargs

        def system_prompt(self, fn):
            return fn

    monkeypatch.setattr(module, "VertexAIImageClient", _FakeVertexAIImageClient, raising=False)
    monkeypatch.setattr(module, "Agent", _FakeAgent)
    monkeypatch.setattr(module, "get_text_model", lambda *args, **kwargs: "text-model", raising=False)
    monkeypatch.setattr(
        module,
        "get_openai_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("specialist agents must not use OpenAI")),
        raising=False,
    )
    monkeypatch.setattr(module, "ImageQualityValidator", lambda *args, **kwargs: object(), raising=False)

    getattr(module, "ImageAgent")()

    assert agent_models == ["text-model", "text-model", "text-model"]


@pytest.mark.parametrize("module_name", _VALIDATOR_MODULES)
def test_image_quality_validators_use_sub2api_vision_client(
    monkeypatch,
    module_name: str,
    tmp_path: Path,
) -> None:
    module = _load_module(module_name)
    captured: dict[str, object] = {}

    class _FakeVisionClient:
        def __init__(self, *args, **kwargs):
            captured["init_kwargs"] = kwargs

        async def analyze_image_bytes_structured(self, **kwargs):
            captured["call_kwargs"] = kwargs
            return module.ImageQualityReview(
                passed=True,
                text_clarity_score=95.0,
                style_score=92.0,
                aspect_ratio_correct=True,
                text_is_chinese=True,
                issues=[],
                summary="ok",
            )

    async def _fake_compress_image_for_review(*args, **kwargs):
        return b"compressed"

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
    monkeypatch.setattr(module, "compress_image_for_review", _fake_compress_image_for_review)

    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake-image")

    review = asyncio.run(module.ImageQualityValidator().validate(image_path, {"topic": "测试主题"}))

    assert review.passed is True
    assert captured["call_kwargs"]["image_bytes"] == b"compressed"
    assert captured["call_kwargs"]["response_model"] is module.ImageQualityReview
    assert captured["call_kwargs"]["system_prompt"]
