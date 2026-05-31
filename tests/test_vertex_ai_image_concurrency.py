from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from src.config.settings import APIConfig
from src.utils.providers.vertex_ai_image import VertexAIImageClient


def test_vertex_ai_image_limits_concurrent_generate_calls(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(APIConfig, "VERTEX_AI_IMAGE_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(VertexAIImageClient, "_semaphore", None, raising=False)
    monkeypatch.setattr(VertexAIImageClient, "_semaphore_limit", None, raising=False)

    lock = threading.Lock()
    active = 0
    max_active = 0

    class FakeModels:
        def generate_content_stream(self, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                yield SimpleNamespace(
                    candidates=[
                        SimpleNamespace(
                            content=SimpleNamespace(
                                parts=[
                                    SimpleNamespace(
                                        inline_data=SimpleNamespace(data=b"fake-png", mime_type="image/png")
                                    )
                                ]
                            )
                        )
                    ]
                )
            finally:
                with lock:
                    active -= 1

    client = VertexAIImageClient.__new__(VertexAIImageClient)
    client.client = SimpleNamespace(models=FakeModels())
    client.model = "gemini-image-test"
    client.image_size = "2K"
    client.aspect_ratio = "3:4"

    async def run_many() -> list[Path]:
        return await asyncio.gather(
            *[
                client.generate_image(
                    prompt="生成图片",
                    output_path=tmp_path / f"image-{index}.png",
                )
                for index in range(5)
            ]
        )

    paths = asyncio.run(run_many())

    assert len(paths) == 5
    assert all(path.exists() for path in paths)
    assert max_active <= 2
