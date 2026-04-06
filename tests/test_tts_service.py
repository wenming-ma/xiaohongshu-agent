import asyncio
from pathlib import Path

from src.agents.video_post.utils.tts.registry import normalize_provider_name
from src.agents.video_post.utils.tts.schemas import (
    TtsSynthesisBatchResult,
    TtsSynthesisContext,
    TtsSynthesisRequest,
    TtsSynthesisResult,
)
from src.agents.video_post.utils.tts.service import TtsService


class _FakeProvider:
    def __init__(self, provider_name: str, behavior):
        self.provider_name = provider_name
        self._behavior = behavior

    async def synthesize_many(self, requests, context):
        return await self._behavior(self.provider_name, requests, context)


def test_normalize_provider_name_supports_aliases() -> None:
    assert normalize_provider_name("") == "fish"
    assert normalize_provider_name("fish_tts") == "fish"
    assert normalize_provider_name("s2.cpp") == "s2cpp"
    assert normalize_provider_name("google_tts") == "google"
    assert normalize_provider_name("qwen_tts") == "qwen"


def test_tts_service_uses_requested_provider(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    async def _behavior(provider_name, requests, context):
        calls.append(provider_name)
        return TtsSynthesisBatchResult(
            requests=requests,
            success_map={
                0: TtsSynthesisResult(
                    audio_path=context.work_dir / "segment.wav",
                    provider_name=provider_name,
                )
            },
            provider_name=provider_name,
        )

    monkeypatch.setattr(
        "src.agents.video_post.utils.tts.service.create_tts_provider",
        lambda provider_name: _FakeProvider(provider_name, _behavior),
    )

    request = TtsSynthesisRequest(segment_index=1, text="你好")
    result = asyncio.run(
        TtsService("google").synthesize_many(
            [request],
            TtsSynthesisContext(work_dir=tmp_path),
        )
    )

    assert calls == ["google"]
    assert result.provider_name == "google"


def test_tts_service_auto_falls_back_after_failure(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    async def _behavior(provider_name, requests, context):
        calls.append(provider_name)
        if provider_name == "fish":
            raise RuntimeError("fish down")
        return TtsSynthesisBatchResult(
            requests=requests,
            success_map={
                0: TtsSynthesisResult(
                    audio_path=context.work_dir / "segment.wav",
                    provider_name=provider_name,
                )
            },
            provider_name=provider_name,
        )

    monkeypatch.setattr(
        "src.agents.video_post.utils.tts.service.create_tts_provider",
        lambda provider_name: _FakeProvider(provider_name, _behavior),
    )

    request = TtsSynthesisRequest(segment_index=1, text="你好")
    result = asyncio.run(
        TtsService("auto").synthesize_many(
            [request],
            TtsSynthesisContext(work_dir=tmp_path),
        )
    )

    assert calls == ["fish", "s2cpp"]
    assert result.provider_name == "s2cpp"


def test_tts_service_auto_skips_empty_provider(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    async def _behavior(provider_name, requests, context):
        calls.append(provider_name)
        if provider_name == "fish":
            return TtsSynthesisBatchResult(
                requests=requests,
                success_map={},
                provider_name=provider_name,
            )
        return TtsSynthesisBatchResult(
            requests=requests,
            success_map={
                0: TtsSynthesisResult(
                    audio_path=context.work_dir / "segment.wav",
                    provider_name=provider_name,
                )
            },
            provider_name=provider_name,
        )

    monkeypatch.setattr(
        "src.agents.video_post.utils.tts.service.create_tts_provider",
        lambda provider_name: _FakeProvider(provider_name, _behavior),
    )

    request = TtsSynthesisRequest(segment_index=1, text="你好")
    result = asyncio.run(
        TtsService("auto").synthesize_many(
            [request],
            TtsSynthesisContext(work_dir=tmp_path),
        )
    )

    assert calls == ["fish", "s2cpp"]
    assert result.provider_name == "s2cpp"


def test_tts_service_auto_falls_back_to_qwen_before_google(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    async def _behavior(provider_name, requests, context):
        calls.append(provider_name)
        if provider_name in {"fish", "s2cpp"}:
            raise RuntimeError(f"{provider_name} down")
        return TtsSynthesisBatchResult(
            requests=requests,
            success_map={
                0: TtsSynthesisResult(
                    audio_path=context.work_dir / "segment.wav",
                    provider_name=provider_name,
                )
            },
            provider_name=provider_name,
        )

    monkeypatch.setattr(
        "src.agents.video_post.utils.tts.service.create_tts_provider",
        lambda provider_name: _FakeProvider(provider_name, _behavior),
    )

    request = TtsSynthesisRequest(segment_index=1, text="你好")
    result = asyncio.run(
        TtsService("auto").synthesize_many(
            [request],
            TtsSynthesisContext(work_dir=tmp_path),
        )
    )

    assert calls == ["fish", "s2cpp", "qwen"]
    assert result.provider_name == "qwen"
