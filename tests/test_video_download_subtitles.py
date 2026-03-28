import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import src.agents.video_post.download.agent as download_agent_module
from src.agents.video_post.download.agent import (
    DEFAULT_FORMAT_SORT,
    DownloadAgent,
)
from src.agents.video_post.schemas import (
    DownloadResult,
    EngagementMetrics,
    Platform,
    SubtitleResult,
    TranscriptionResult,
    VideoSource,
)


def _build_download_result(video_path: Path) -> DownloadResult:
    return DownloadResult(
        success=True,
        source=VideoSource(
            url="https://example.com/video",
            platform=Platform.YOUTUBE,
            title="demo",
            description="demo",
            engagement=EngagementMetrics(),
        ),
        local_path=str(video_path),
        file_size_bytes=1024,
        format="mp4",
    )


def test_download_with_ytdlp_does_not_request_subtitles(monkeypatch, tmp_path: Path) -> None:
    created_opts: list[dict] = []

    class _FakeYoutubeDL:
        def __init__(self, opts: dict):
            self.opts = opts
            created_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url: str, download: bool = True):
            video_path = Path(self.opts["outtmpl"]).parent / "demo.mp4"
            video_path.write_bytes(b"video")
            return {"title": "demo", "ext": "mp4"}

        def prepare_filename(self, info: dict) -> str:
            return str(Path(self.opts["outtmpl"]).parent / "demo.mp4")

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=_FakeYoutubeDL))

    agent = DownloadAgent()
    source = VideoSource(
        url="https://example.com/watch?v=1",
        platform=Platform.YOUTUBE,
        title="demo",
        description="demo",
        engagement=EngagementMetrics(),
    )

    video_path = asyncio.run(agent._download_with_ytdlp(source, tmp_path))

    assert video_path.name == "demo.mp4"
    assert len(created_opts) == 1
    opts = created_opts[0]
    assert "writesubtitles" not in opts
    assert "writeautomaticsub" not in opts
    assert "subtitleslangs" not in opts
    assert "subtitlesformat" not in opts
    assert opts["format_sort"] == DEFAULT_FORMAT_SORT
    assert opts["format_sort_force"] is True


def test_transcribe_text_only_ignores_existing_sidecar_subtitles(monkeypatch, tmp_path: Path) -> None:
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    (tmp_path / "sample.zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n旧字幕\n", encoding="utf-8")

    class _FakeTranscriber:
        async def transcribe(self, _video_path: Path) -> TranscriptionResult:
            return TranscriptionResult(success=True, transcript="whisper transcript", language="en")

    monkeypatch.setattr(download_agent_module, "AudioTranscriber", lambda: _FakeTranscriber())

    agent = DownloadAgent()
    result = _build_download_result(video_path)
    transcribed = asyncio.run(agent._transcribe_text_only(result))

    assert transcribed.transcription is not None
    assert transcribed.transcription.transcript == "whisper transcript"
    assert transcribed.transcription.language == "en"


def test_transcribe_uses_subtitle_generator_even_when_sidecar_exists(monkeypatch, tmp_path: Path) -> None:
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    (tmp_path / "sample.zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n旧字幕\n", encoding="utf-8")

    subtitle_path = tmp_path / "sample_subtitled.srt"
    tts_path = tmp_path / "sample_subtitled_tts.srt"
    called = {"generate": 0}
    constructor_kwargs: dict = {}

    class _FakeSubtitleGenerator:
        def __init__(self, **kwargs):
            constructor_kwargs.update(kwargs)

        async def generate_and_burn(self, video_path: Path, output_path: Path, **kwargs) -> SubtitleResult:
            called["generate"] += 1
            subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
            tts_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n[neutral] 你好\n", encoding="utf-8")
            return SubtitleResult(
                success=True,
                language="en",
                translated=True,
                srt_path=str(subtitle_path),
                tts_srt_path=str(tts_path),
                video_with_subs=str(output_path),
            )

    monkeypatch.setattr(
        download_agent_module,
        "SubtitleGenerator",
        lambda *args, **kwargs: _FakeSubtitleGenerator(**kwargs),
    )

    agent = DownloadAgent()
    result = _build_download_result(video_path)
    result.transcription = TranscriptionResult(success=True, transcript="already here", language="en")

    transcribed = asyncio.run(agent._transcribe(result))

    assert called["generate"] == 1
    assert constructor_kwargs["translation_agent"] is agent.subtitle_translation_agent
    assert constructor_kwargs["translation_reviewer"] is agent.subtitle_translation_reviewer
    assert transcribed.subtitle is not None
    assert transcribed.subtitle.tts_srt_path == str(tts_path)
