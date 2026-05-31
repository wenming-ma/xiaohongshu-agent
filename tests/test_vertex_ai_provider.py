import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import google.auth
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str):
    for name in (
        "src.utils.providers",
        "src.utils.providers.vertex_ai_common",
        "src.utils.providers.vertex_ai_image",
        "src.utils.providers.vertex_ai_vision",
    ):
        sys.modules.pop(name, None)

    package_roots = {
        "src": _REPO_ROOT / "src",
        "src.utils": _REPO_ROOT / "src" / "utils",
        "src.utils.providers": _REPO_ROOT / "src" / "utils" / "providers",
    }
    for package_name, package_path in package_roots.items():
        package_module = sys.modules.get(package_name) or types.ModuleType(package_name)
        package_module.__path__ = [str(package_path)]
        sys.modules[package_name] = package_module
        if "." in package_name:
            parent_name, child_name = package_name.rsplit(".", 1)
            setattr(sys.modules[parent_name], child_name, package_module)

    module_path = _REPO_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_vertex_ai_image_client_uses_adc_project_and_reference_images(monkeypatch, tmp_path: Path) -> None:
    common = _load_module("src.utils.providers.vertex_ai_common")
    module = _load_module("src.utils.providers.vertex_ai_image")
    captured: dict[str, object] = {}

    class _FakeModels:
        def generate_content_stream(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            inline_data = types.SimpleNamespace(data=b"fake-image", mime_type="image/png")
            part = types.SimpleNamespace(inline_data=inline_data, text=None)
            candidate = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]))
            yield types.SimpleNamespace(candidates=[candidate])

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = _FakeModels()

    monkeypatch.setattr(common.APIConfig, "VERTEX_AI_PROJECT_ID", None)
    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_IMAGE_MODEL", "gemini-2.5-flash-image")
    monkeypatch.setattr(module.APIConfig, "GEMINI_IMAGE_SIZE", "2K")
    monkeypatch.setattr(common, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("VERTEX_AI_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    monkeypatch.setattr(google.auth, "default", lambda *args, **kwargs: (object(), "adc-project"))
    monkeypatch.setattr(
        module,
        "build_vertex_client",
        lambda **kwargs: (
            _FakeClient(project=common.resolve_vertex_project(kwargs.get("project"))),
            common.resolve_vertex_project(kwargs.get("project")),
            "global",
        ),
    )

    ref_path = tmp_path / "reference.png"
    ref_path.write_bytes(b"ref-bytes")

    client = module.VertexAIImageClient()
    output_path = asyncio.run(
        client.generate_image(
            prompt="draw a cover",
            output_path=tmp_path / "cover.png",
            aspect_ratio="16:9",
            reference_images=[("bag", ref_path)],
        )
    )

    assert client.project == "adc-project"
    assert captured["client_kwargs"]["project"] == "adc-project"
    assert output_path.exists()
    assert output_path.read_bytes() == b"fake-image"
    assert captured["generate_kwargs"]["model"] == "gemini-2.5-flash-image"
    config = captured["generate_kwargs"]["config"]
    assert config.response_modalities == ["IMAGE", "TEXT"]
    assert config.image_config.image_size == "2K"
    assert config.image_config.aspect_ratio == "16:9"
    parts = captured["generate_kwargs"]["contents"][0].parts
    assert parts[0].text == "[Reference image: bag]"
    assert parts[1].inline_data.data == b"ref-bytes"
    assert parts[-1].text == "draw a cover"


def test_vertex_ai_vision_client_returns_structured_output(monkeypatch, tmp_path: Path) -> None:
    module = _load_module("src.utils.providers.vertex_ai_vision")
    captured: dict[str, object] = {}

    class VisionResult(BaseModel):
        extracted_text: str
        has_text: bool

    class _FakeModels:
        def generate_content(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return types.SimpleNamespace(text='{"extracted_text":"HELLO123","has_text":true}')

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = _FakeModels()

    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_PROJECT_ID", "vertex-project")
    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_VISION_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        module,
        "build_vertex_client",
        lambda **kwargs: (_FakeClient(project="vertex-project"), "vertex-project", "global"),
    )

    image_path = tmp_path / "vision.jpg"
    image_path.write_bytes(b"fake-jpeg")

    client = module.VertexAIVisionClient()
    result = asyncio.run(
        client.analyze_image_structured(
            image_path=image_path,
            prompt="请读取图片文字",
            response_model=VisionResult,
            media_type="image/jpeg",
            system_prompt="你是 OCR 助手",
        )
    )

    assert result == VisionResult(extracted_text="HELLO123", has_text=True)
    assert captured["client_kwargs"]["project"] == "vertex-project"
    assert captured["generate_kwargs"]["model"] == "gemini-2.5-flash"
    config = captured["generate_kwargs"]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is VisionResult
    assert config.system_instruction == "你是 OCR 助手"
    parts = captured["generate_kwargs"]["contents"][0].parts
    assert parts[0].text == "请读取图片文字"
    assert parts[1].inline_data.data == b"fake-jpeg"


def test_vertex_ai_vision_client_accepts_labeled_multi_image_structured_input(monkeypatch, tmp_path: Path) -> None:
    module = _load_module("src.utils.providers.vertex_ai_vision")
    captured: dict[str, object] = {}

    class VisionResult(BaseModel):
        aligned: bool

    class _FakeModels:
        def generate_content(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return types.SimpleNamespace(text='{"aligned":true}')

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = _FakeModels()

    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_PROJECT_ID", "vertex-project")
    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_VISION_MODEL", "gemini-3.1-pro")
    monkeypatch.setattr(
        module,
        "build_vertex_client",
        lambda **kwargs: (_FakeClient(project="vertex-project"), "vertex-project", "global"),
    )

    generated = tmp_path / "generated.jpg"
    generated.write_bytes(b"generated-bytes")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference-bytes")

    client = module.VertexAIVisionClient()
    result = asyncio.run(
        client.analyze_images_structured(
            images=[("generated", generated), ("reference_1", reference)],
            prompt="判断生成图是否保留参考物品",
            response_model=VisionResult,
            system_prompt="你是视觉一致性审核员",
        )
    )

    assert result == VisionResult(aligned=True)
    assert captured["generate_kwargs"]["model"] == "gemini-3.1-pro"
    config = captured["generate_kwargs"]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is VisionResult
    assert config.system_instruction == "你是视觉一致性审核员"
    parts = captured["generate_kwargs"]["contents"][0].parts
    assert parts[0].text == "判断生成图是否保留参考物品"
    assert parts[1].text == "[Image: generated]"
    assert parts[2].inline_data.data == b"generated-bytes"
    assert parts[3].text == "[Image: reference_1]"
    assert parts[4].inline_data.data == b"reference-bytes"


def test_vertex_ai_vision_client_returns_plain_text(monkeypatch, tmp_path: Path) -> None:
    module = _load_module("src.utils.providers.vertex_ai_vision")
    captured: dict[str, object] = {}

    class _FakeModels:
        def generate_content(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return types.SimpleNamespace(text="识别到 HELLO123")

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = _FakeModels()

    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_PROJECT_ID", "vertex-project")
    monkeypatch.setattr(module.APIConfig, "VERTEX_AI_VISION_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        module,
        "build_vertex_client",
        lambda **kwargs: (_FakeClient(project="vertex-project"), "vertex-project", "global"),
    )

    image_path = tmp_path / "vision.png"
    image_path.write_bytes(b"fake-png")

    client = module.VertexAIVisionClient()
    result = asyncio.run(
        client.analyze_image(
            image_path=image_path,
            prompt="请描述图片",
            media_type="image/png",
        )
    )

    assert result == "识别到 HELLO123"
    assert captured["generate_kwargs"]["config"].response_mime_type is None
