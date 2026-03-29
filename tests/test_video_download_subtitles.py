import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import src.agents.video_post.download.agent as download_agent_module
from src.agents.shared.utils.asr.types import TranscriptionResult
from src.agents.video_post.download.agent import (
    DEFAULT_FORMAT_SORT,
    MAX_FILE_SIZE,
    DownloadAgent,
    TARGET_DOWNLOAD_SHORT_EDGE,
    _extract_selected_video_short_edge,
    _estimate_selected_download_size,
)
from src.agents.video_post.schemas import (
    DownloadResult,
    EngagementMetrics,
    Platform,
    SubtitleResult,
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
            if not download:
                return {
                    "format_id": "399+251",
                    "requested_formats": [
                        {"filesize": 200 * 1024 * 1024},
                        {"filesize": 20 * 1024 * 1024},
                    ],
                }
            video_path = Path(self.opts["outtmpl"]).parent / "demo.mp4"
            video_path.write_bytes(b"video")
            return {"title": "demo", "ext": "mp4", "format_id": self.opts["format"]}

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
    assert len(created_opts) == 2
    probe_opts = created_opts[0]
    download_opts = created_opts[1]
    assert "writesubtitles" not in probe_opts
    assert "writeautomaticsub" not in probe_opts
    assert "subtitleslangs" not in probe_opts
    assert "subtitlesformat" not in probe_opts
    assert probe_opts["format_sort"] == DEFAULT_FORMAT_SORT
    assert probe_opts["format_sort_force"] is True
    assert download_opts["format"] == "399+251"
    assert "format_sort" not in download_opts
    assert "format_sort_force" not in download_opts


def test_download_with_ytdlp_falls_back_to_lower_resolution_when_probe_is_too_large(
    monkeypatch,
    tmp_path: Path,
) -> None:
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
            if not download:
                return {
                    "format_id": "399+251",
                    "requested_formats": [
                        {
                            "filesize": MAX_FILE_SIZE - 10 * 1024 * 1024,
                            "width": 1920,
                            "height": 1080,
                            "vcodec": "av01.0.08M.08",
                        },
                        {
                            "filesize": 32 * 1024 * 1024,
                            "vcodec": "none",
                            "acodec": "opus",
                        },
                    ],
                }

            video_path = Path(self.opts["outtmpl"]).parent / "demo.mp4"
            video_path.write_bytes(b"video")
            return {"title": "demo", "ext": "mp4", "format_id": self.opts["format"]}

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

    try:
        asyncio.run(agent._download_with_ytdlp(source, tmp_path))
        raise AssertionError("expected download size guard to fail")
    except RuntimeError as exc:
        assert "1080p+" in str(exc)

    assert len(created_opts) == 1
    assert created_opts[0]["format_sort"] == DEFAULT_FORMAT_SORT


def test_download_with_ytdlp_rejects_below_1080p_probe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class _FakeYoutubeDL:
        def __init__(self, opts: dict):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url: str, download: bool = True):
            return {
                "format_id": "398+140",
                "requested_formats": [
                    {"filesize": 260 * 1024 * 1024, "width": 1280, "height": 720, "vcodec": "av01"},
                    {"filesize": 20 * 1024 * 1024, "vcodec": "none", "acodec": "aac"},
                ],
            }

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

    try:
        asyncio.run(agent._download_with_ytdlp(source, tmp_path))
        raise AssertionError("expected 1080p guard to fail")
    except RuntimeError as exc:
        assert "不低于 1080p" in str(exc)


def test_estimate_selected_download_size_sums_requested_formats() -> None:
    info = {
        "requested_formats": [
            {"filesize": 123},
            {"filesize_approx": 456},
        ]
    }

    assert _estimate_selected_download_size(info) == 579


def test_extract_selected_video_short_edge_reads_requested_video_format() -> None:
    info = {
        "requested_formats": [
            {"vcodec": "none", "acodec": "aac"},
            {"vcodec": "av01", "width": 1080, "height": 1920},
        ]
    }

    assert _extract_selected_video_short_edge(info) == TARGET_DOWNLOAD_SHORT_EDGE


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
    assert constructor_kwargs["subtitle_translation_agent"] is agent.subtitle_translation_agent
    assert transcribed.subtitle is not None
    assert transcribed.subtitle.tts_srt_path == str(tts_path)
