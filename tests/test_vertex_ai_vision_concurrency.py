from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

from src.config.settings import APIConfig
from src.utils.providers.vertex_ai_vision import VertexAIVisionClient


def test_vertex_ai_vision_limits_concurrent_generate_calls(monkeypatch) -> None:
    monkeypatch.setattr(APIConfig, "VERTEX_AI_VISION_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(VertexAIVisionClient, "_semaphore", None, raising=False)
    monkeypatch.setattr(VertexAIVisionClient, "_semaphore_limit", None, raising=False)

    lock = threading.Lock()
    active = 0
    max_active = 0

    class FakeModels:
        def generate_content(self, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                return SimpleNamespace(text="ok")
            finally:
                with lock:
                    active -= 1

    client = VertexAIVisionClient.__new__(VertexAIVisionClient)
    client.client = SimpleNamespace(models=FakeModels())
    client.model = "gemini-test"

    async def run_many() -> list[str]:
        return await asyncio.gather(
            *[
                client.analyze_image_bytes(
                    image_bytes=b"image",
                    prompt="describe",
                    media_type="image/jpeg",
                )
                for _ in range(5)
            ]
        )

    assert asyncio.run(run_many()) == ["ok"] * 5
    assert max_active <= 2
