import base64
import asyncio
import importlib.util
from pathlib import Path

import pytest
from pydantic import BaseModel


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "src" / "utils" / "providers" / "sub2api.py"
    spec = importlib.util.spec_from_file_location("test_sub2api_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_sub2api_model_uses_responses_api_defaults(monkeypatch) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    class FakeOpenAIProvider:
        def __init__(self, openai_client):
            captured["provider_client"] = openai_client

    class FakeResponsesModel:
        def __init__(self, model_name, *, provider, settings=None):
            captured["model_name"] = model_name
            captured["provider"] = provider
            captured["settings"] = settings

    monkeypatch.setattr(module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(module, "OpenAIProvider", FakeOpenAIProvider)
    monkeypatch.setattr(module, "OpenAIResponsesModel", FakeResponsesModel)
    monkeypatch.setattr(module, "_shared_provider", None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SUB2API_BASE_URL", "https://api.xiaojiu.one")
    monkeypatch.setenv("SUB2API_VISION_MODEL", "gpt-5.5")
    monkeypatch.setenv("SUB2API_REASONING_EFFORT", "xhigh")

    model = module.get_sub2api_model()

    assert captured["client_kwargs"]["api_key"] == "test-key"
    assert captured["client_kwargs"]["base_url"] == "https://api.xiaojiu.one/v1"
    assert captured["client_kwargs"]["max_retries"] == 0
    assert captured["model_name"] == "gpt-5.5"
    assert captured["settings"] == {
        "openai_reasoning_effort": "xhigh",
        "openai_send_reasoning_ids": False,
        "openai_previous_response_id": "auto",
        "openai_truncation": "auto",
    }
    assert model is not None


def test_sub2api_model_selection_splits_vision_and_image(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setenv("SUB2API_VISION_MODEL", "gpt-5.5")
    monkeypatch.setenv("SUB2API_IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("SUB2API_MODEL", "gpt-5.4")

    assert module._get_vision_model() == "gpt-5.5"
    assert module._get_image_model() == "gpt-image-2"


def test_sub2api_image_model_defaults_to_gpt_image_2(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.delenv("SUB2API_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("SUB2API_VISION_MODEL", raising=False)
    monkeypatch.delenv("SUB2API_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    assert module._get_image_model() == "gpt-image-2"


def test_sub2api_image_client_saves_generated_image(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    png_bytes = base64.b64encode(b"fake-png")
    captured: dict[str, object] = {}

    class FakeImageGenerationCall:
        type = "image_generation_call"
        result = png_bytes.decode("ascii")
        status = "completed"

    class FakeResponse:
        output = [FakeImageGenerationCall()]

    class FakeResponsesAPI:
        async def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeResponse()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.responses = FakeResponsesAPI()

    monkeypatch.setattr(module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SUB2API_BASE_URL", "https://api.xiaojiu.one")
    monkeypatch.setenv("SUB2API_IMAGE_MODEL", "gpt-image-2")

    client = module.Sub2APIImageClient()
    output_path = asyncio.run(
        client.generate_image(
            prompt="draw a cover",
            output_path=tmp_path / "cover.png",
            aspect_ratio="16:9",
        )
    )

    assert output_path.exists()
    assert output_path.read_bytes() == b"fake-png"
    assert captured["client_kwargs"]["base_url"] == "https://api.xiaojiu.one/v1"
    assert captured["client_kwargs"]["max_retries"] == 0
    assert captured["create_kwargs"]["model"] == "gpt-image-2"
    assert captured["create_kwargs"]["tools"][0]["type"] == "image_generation"
    assert captured["create_kwargs"]["tools"][0]["size"] == "1536x1024"
    assert "input_fidelity" not in captured["create_kwargs"]["tools"][0]
    assert "reasoning" not in captured["create_kwargs"]


def test_sub2api_image_client_includes_reference_images(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    recorded_inputs: dict[str, object] = {}

    class FakeResponse:
        output = []

    class FakeResponsesAPI:
        async def create(self, **kwargs):
            recorded_inputs["input"] = kwargs["input"]
            return FakeResponse()

    class FakeAsyncOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponsesAPI()

    monkeypatch.setattr(module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    ref_path = tmp_path / "ref.jpg"
    ref_path.write_bytes(b"jpeg-bytes")

    client = module.Sub2APIImageClient()

    with pytest.raises(ValueError, match="Sub2API 未返回图片数据"):
        asyncio.run(
            client.generate_image(
                prompt="draw a bag",
                output_path=tmp_path / "out.png",
                reference_images=[("bag", ref_path)],
            )
        )

    content = recorded_inputs["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "[Reference image: bag]"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert content[-1] == {"type": "input_text", "text": "draw a bag"}
    assert "input_fidelity" not in recorded_inputs.get("tool", {})


def test_sub2api_vision_client_reads_image_via_responses_api(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    class FakeOutputText:
        type = "output_text"
        text = "识别到 HELLO123 和 RED BAG"

    class FakeMessage:
        type = "message"
        content = [FakeOutputText()]

    class FakeResponse:
        output = [FakeMessage()]

    class FakeResponsesAPI:
        async def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeResponse()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.responses = FakeResponsesAPI()

    monkeypatch.setattr(module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SUB2API_BASE_URL", "https://api.xiaojiu.one")
    monkeypatch.setenv("SUB2API_VISION_MODEL", "gpt-5.5")

    image_path = tmp_path / "vision.png"
    image_path.write_bytes(b"fake-png")

    client = module.Sub2APIVisionClient()
    result = asyncio.run(
        client.analyze_image(
            image_path=image_path,
            prompt="请读取图片文字",
            media_type="image/png",
            system_prompt="你是 OCR 助手",
        )
    )

    assert result == "识别到 HELLO123 和 RED BAG"
    assert captured["client_kwargs"]["base_url"] == "https://api.xiaojiu.one/v1"
    assert captured["client_kwargs"]["max_retries"] == 0
    assert captured["create_kwargs"]["model"] == "gpt-5.5"
    assert captured["create_kwargs"]["reasoning"] == {"effort": "xhigh"}
    assert captured["create_kwargs"]["input"][0]["role"] == "system"
    assert captured["create_kwargs"]["input"][1]["role"] == "user"
    user_content = captured["create_kwargs"]["input"][1]["content"]
    assert user_content[0] == {"type": "input_text", "text": "请读取图片文字"}
    assert user_content[1]["type"] == "input_image"
    assert user_content[1]["image_url"].startswith("data:image/png;base64,")


def test_sub2api_vision_client_returns_structured_output(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    class VisionResult(BaseModel):
        extracted_text: str
        has_text: bool

    class FakeOutputText:
        type = "output_text"
        text = '{"extracted_text":"HELLO123","has_text":true}'

    class FakeMessage:
        type = "message"
        content = [FakeOutputText()]

    class FakeResponse:
        output = [FakeMessage()]

    class FakeResponsesAPI:
        async def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeResponse()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.responses = FakeResponsesAPI()

    monkeypatch.setattr(module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("SUB2API_BASE_URL", "https://api.xiaojiu.one")
    monkeypatch.setenv("SUB2API_VISION_MODEL", "gpt-5.5")

    image_path = tmp_path / "vision.png"
    image_path.write_bytes(b"fake-png")

    client = module.Sub2APIVisionClient()
    result = asyncio.run(
        client.analyze_image_structured(
            image_path=image_path,
            prompt="请读取图片文字",
            response_model=VisionResult,
            media_type="image/png",
            system_prompt="你是 OCR 助手",
        )
    )

    assert result == VisionResult(extracted_text="HELLO123", has_text=True)
    assert captured["create_kwargs"]["text"]["format"]["type"] == "json_schema"
    assert captured["create_kwargs"]["text"]["format"]["name"] == "visionresult"
    assert captured["create_kwargs"]["text"]["format"]["strict"] is True
