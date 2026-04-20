import importlib

import pytest


_VISION_MODULES = (
    "src.agents.image_post.research.tools",
    "src.agents.styled_image_post.research.tools",
    "src.agents.outfit_post.research.tools",
)


@pytest.mark.parametrize("module_name", _VISION_MODULES)
def test_image_reader_agents_request_gemini_25_pro_for_vision(monkeypatch, module_name: str) -> None:
    module = importlib.import_module(module_name)
    google_model_calls: list[str | None] = []

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            self.model = kwargs.get("model")

    def fake_get_google_model(model_name: str | None = None):
        google_model_calls.append(model_name)
        return f"vision:{model_name}"

    monkeypatch.setattr(module, "Agent", _FakeAgent)
    monkeypatch.setattr(module, "get_google_model", fake_get_google_model)

    module.ImageReaderAgent()
    module.PostImageReaderAgent(mcp_server=object())

    assert google_model_calls == ["gemini-2.5-pro", "gemini-2.5-pro"]
