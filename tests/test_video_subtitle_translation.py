import asyncio
from pathlib import Path

from src.agents.video_post.download.subtitle import (
    SubtitleSegment,
    SubtitleGenerator,
)


class _FakeTranslationAgent:
    """Fake that mimics SubtitleTranslationAgent.forward() interface."""

    def __init__(self, results: list[list[SubtitleSegment]]):
        self._results = list(results)
        self.calls: list[tuple[int, str, bool]] = []

    async def forward(
        self,
        segments: list[SubtitleSegment],
        *,
        source_language: str,
        translate_first: bool = True,
    ) -> list[SubtitleSegment]:
        self.calls.append((len(segments), source_language, translate_first))
        return self._results.pop(0) if self._results else segments


def _segs(*texts: str) -> list[SubtitleSegment]:
    return [
        SubtitleSegment(start=float(i), end=float(i) + 1.0, text=t)
        for i, t in enumerate(texts)
    ]


def test_translate_segments_delegates_to_agent() -> None:
    translated = _segs("继续搅拌均匀")
    fake = _FakeTranslationAgent([translated])
    generator = SubtitleGenerator(subtitle_translation_agent=fake)

    result = asyncio.run(
        generator._translate_segments_for_chinese_tts(
            _segs("keep stirring"),
            source_language="en",
            translate_first=True,
        )
    )

    assert result[0].text == "继续搅拌均匀"
    assert fake.calls == [(1, "en", True)]


def test_translate_segments_passes_translate_first_false_for_zh() -> None:
    translated = _segs("大家慢慢搅拌均匀")
    fake = _FakeTranslationAgent([translated])
    generator = SubtitleGenerator(subtitle_translation_agent=fake)

    result = asyncio.run(
        generator._translate_segments_for_chinese_tts(
            _segs("mix it gently"),
            source_language="zh",
            translate_first=False,
        )
    )

    assert result[0].text == "大家慢慢搅拌均匀"
    assert fake.calls == [(1, "zh", False)]


def test_translate_passthrough_preserves_natural_chinese() -> None:
    original = _segs("这个 app 的通知先打开")
    fake = _FakeTranslationAgent([original])
    generator = SubtitleGenerator(subtitle_translation_agent=fake)

    result = asyncio.run(
        generator._translate_segments_for_chinese_tts(
            original,
            source_language="zh",
            translate_first=False,
        )
    )

    assert result[0].text == "这个 app 的通知先打开"


def test_generate_and_burn_always_writes_dedicated_tts_srt(tmp_path: Path) -> None:
    translated = _segs("现在开始慢慢搅拌均匀然后继续搅拌到完全顺滑最后再把表面的小气泡轻轻整理掉")
    # Override timing to match source segment
    translated[0].start = 0.0
    translated[0].end = 2.0
    translated[0].tone_tag = "neutral"

    fake = _FakeTranslationAgent([translated])
    generator = SubtitleGenerator(subtitle_translation_agent=fake)

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"audio")

    async def _fake_extract_audio(_video_path: Path) -> Path:
        return audio_path

    async def _fake_transcribe(_audio_path: Path):
        return [SubtitleSegment(start=0.0, end=2.0, text="keep stirring until smooth")], "en"

    async def _fake_assign_speakers(segments, _audio_path):
        return segments

    async def _fake_burn_subtitles(_video_path: Path, _srt_path: Path, _output_path: Path, **_kwargs) -> None:
        return None

    generator._extract_audio = _fake_extract_audio  # type: ignore[method-assign]
    generator._transcribe_audio = _fake_transcribe  # type: ignore[method-assign]
    generator._assign_speakers = _fake_assign_speakers  # type: ignore[method-assign]
    generator._burn_subtitles = _fake_burn_subtitles  # type: ignore[method-assign]

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    output_path = tmp_path / "sample_subtitled.mp4"

    result = asyncio.run(generator.generate_and_burn(video_path, output_path, target_language="zh"))

    assert result.success is True
    assert result.tts_srt_path != result.srt_path
    tts_path = Path(result.tts_srt_path)
    assert tts_path.exists()

    tts_text = tts_path.read_text(encoding="utf-8")
    assert "[neutral]" in tts_text
    assert tts_text.count("\n\n") >= 2
