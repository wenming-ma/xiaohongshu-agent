import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.agents.shared.utils.asr.service as service_module
from src.agents.shared.utils.asr.alignment.base import AlignmentResult
from src.agents.shared.utils.asr.model_sources import (
    COHERE_ASR_MODEL_SPEC,
    QWEN_ASR_MODEL_SPEC,
    resolve_model_source_from_root,
)
from src.agents.shared.utils.asr.providers.cohere import CohereAsrProvider
from src.agents.shared.utils.asr.providers.qwen import QwenAsrProvider
from src.agents.shared.utils.asr.schemas import TranscriptionResult, TranscriptionSegment


class _FakeProvider:
    def __init__(self, result: TranscriptionResult):
        self.result = result
        self.released = False

    def transcribe_audio(self, _audio_path: Path) -> TranscriptionResult:
        return self.result

    def release(self) -> None:
        self.released = True


class _FakeLanguageDetector:
    def detect_language(self, _audio_path: Path) -> str:
        return "en"

    def release(self) -> None:
        pass


class _FakeAligner:
    def align(self, *, audio_path: Path, transcript: str, language: str) -> AlignmentResult:
        del audio_path, transcript
        return AlignmentResult(
            language=language,
            duration_seconds=4,
            segments=[
                TranscriptionSegment(start=0.0, end=1.0, text="fresh transcript"),
                TranscriptionSegment(start=1.0, end=4.0, text="from cohere"),
            ],
        )

    def release(self) -> None:
        pass


def _write_stub_files(model_dir: Path, filenames: tuple[str, ...]) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        (model_dir / filename).write_text("stub", encoding="utf-8")


def test_get_asr_service_uses_configured_provider(monkeypatch) -> None:
    service_module.release_asr_resources()
    monkeypatch.setattr(service_module.ASRConfig, "PROVIDER", "cohere")

    service = service_module.get_asr_service()

    assert service.provider_name == "cohere"
    service_module.release_asr_resources()


def test_get_asr_service_defaults_to_qwen(monkeypatch) -> None:
    service_module.release_asr_resources()
    monkeypatch.setattr(service_module.ASRConfig, "PROVIDER", "qwen")

    service = service_module.get_asr_service()

    assert service.provider_name == "qwen"
    service_module.release_asr_resources()


def test_asr_service_fills_timestamp_contract_from_plain_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"audio")
    fake_provider = _FakeProvider(
        TranscriptionResult(
            success=True,
            transcript="hello world",
            language="en",
            duration_seconds=7,
        )
    )

    service = service_module.AsrService("fake")
    with patch("src.agents.shared.utils.asr.service.create_asr_provider", return_value=fake_provider):
        result = asyncio.run(service.transcribe_audio(audio_path))

    assert result.success is True
    assert result.transcript == "hello world"
    assert len(result.segments) == 1
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 7.0
    assert result.segments[0].text == "hello world"


def test_cohere_provider_uses_reference_segments_to_build_timestamped_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio")
    provider = CohereAsrProvider(
        language_detector=_FakeLanguageDetector(),
        timestamp_aligner=_FakeAligner(),
    )
    monkeypatch.setattr(provider, "_transcribe_text", lambda _path, _language: "fresh transcript from cohere")

    result = provider.transcribe_audio(audio_path)

    assert result.success is True
    assert result.language == "en"
    assert result.transcript == "fresh transcript from cohere"
    assert len(result.segments) == 2
    assert result.segments[0].start == 0.0
    assert result.segments[-1].end == 4.0


def test_resolve_model_source_from_root_supports_snapshot_only_layout(tmp_path: Path) -> None:
    model_root = tmp_path / "models--CohereLabs--cohere-transcribe-03-2026"
    snapshots_dir = model_root / "snapshots"
    older_snapshot = snapshots_dir / "older"
    newer_snapshot = snapshots_dir / "newer"
    _write_stub_files(older_snapshot, COHERE_ASR_MODEL_SPEC.required_files)
    _write_stub_files(newer_snapshot, COHERE_ASR_MODEL_SPEC.required_files)

    result, download_root = resolve_model_source_from_root(
        model_root,
        repo_id=COHERE_ASR_MODEL_SPEC.repo_id,
        required_files=COHERE_ASR_MODEL_SPEC.required_files,
        cache_dir=tmp_path,
    )

    assert result == str(newer_snapshot)
    assert download_root is None


def test_qwen_provider_returns_timestamped_segments(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio")
    provider = QwenAsrProvider()

    fake_result = SimpleNamespace(
        language="English",
        text="hello world.",
        time_stamps=[
            SimpleNamespace(text="hello", start_time=0.0, end_time=0.4),
            SimpleNamespace(text="world.", start_time=0.45, end_time=1.1),
        ],
    )
    fake_model = SimpleNamespace(
        transcribe=lambda **kwargs: (
            [fake_result]
            if kwargs["audio"] == [str(audio_path)]
            and kwargs["language"] is None
            and kwargs["return_time_stamps"] is True
            else []
        )
    )
    monkeypatch.setattr(provider, "_load_model", lambda: fake_model)

    result = provider.transcribe_audio(audio_path)

    assert result.success is True
    assert result.language == "en"
    assert result.transcript == "hello world."
    assert len(result.segments) == 1
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 1.1
    assert result.segments[0].text == "hello world."


def test_qwen_provider_requires_cuda_torch() -> None:
    provider = QwenAsrProvider()
    fake_torch = SimpleNamespace(
        __version__="2.11.0+cpu",
        version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(is_available=lambda: False),
        float16="float16",
        bfloat16="bfloat16",
        float32="float32",
    )

    with patch.dict("sys.modules", {"torch": fake_torch}):
        with pytest.raises(RuntimeError, match="仅支持 GPU 运行"):
            provider._resolve_dtype_and_device()


def test_resolve_model_source_from_root_supports_qwen_snapshot_layout(tmp_path: Path) -> None:
    model_root = tmp_path / "models--Qwen--Qwen3-ASR-1.7B"
    snapshot_dir = model_root / "snapshots" / "current"
    _write_stub_files(snapshot_dir, QWEN_ASR_MODEL_SPEC.required_files)

    result, download_root = resolve_model_source_from_root(
        model_root,
        repo_id=QWEN_ASR_MODEL_SPEC.repo_id,
        required_files=QWEN_ASR_MODEL_SPEC.required_files,
        cache_dir=tmp_path,
    )

    assert result == str(snapshot_dir)
    assert download_root is None
