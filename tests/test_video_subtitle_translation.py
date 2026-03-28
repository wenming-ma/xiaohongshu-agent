import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.utils.subtitle_generator import (
    SubtitleSegment,
    SubtitleTranslationReview,
    TranslationBatch,
    TranslationLine,
    WhisperSubtitleGenerator,
)


class _FakeAgent:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    async def run(self, prompt: str, *args, **kwargs):
        self.prompts.append(prompt)
        output = self._outputs.pop(0)
        return SimpleNamespace(output=output)


def _batch(*texts: str) -> TranslationBatch:
    return TranslationBatch(
        lines=[
            TranslationLine(index=index + 1, tone_tag="neutral", text=text)
            for index, text in enumerate(texts)
        ]
    )


def test_translate_segments_retries_with_review_feedback() -> None:
    generator = WhisperSubtitleGenerator()
    generator.translation_agent = _FakeAgent(
        [
            _batch("keep stirring"),
            _batch("继续搅拌均匀"),
        ]
    )
    generator.translation_reviewer = _FakeAgent(
        [
            SubtitleTranslationReview(
                passed=False,
                summary="第1行仍有英文残留",
                issues=["第1行还保留了英文 keep stirring"],
            ),
            SubtitleTranslationReview(passed=True, summary="全部通过"),
        ]
    )

    segments = [SubtitleSegment(start=0.0, end=1.5, text="keep stirring")]
    translated = asyncio.run(
        generator._translate_segments_for_chinese_tts(
            segments,
            source_language="en",
            translate_first=True,
        )
    )

    assert translated[0].text == "继续搅拌均匀"
    assert len(generator.translation_agent.prompts) == 2
    assert "审核反馈" in generator.translation_agent.prompts[1]
    assert len(generator.translation_reviewer.prompts) == 2


def test_translate_segments_reviews_zh_detected_input_and_revises() -> None:
    generator = WhisperSubtitleGenerator()
    generator.translation_agent = _FakeAgent([_batch("大家慢慢搅拌均匀")])
    generator.translation_reviewer = _FakeAgent(
        [
            SubtitleTranslationReview(
                passed=False,
                summary="当前字幕不适合中文口播",
                issues=["第1行不是自然中文，请改成中文表达"],
            ),
            SubtitleTranslationReview(passed=True, summary="全部通过"),
        ]
    )

    segments = [SubtitleSegment(start=0.0, end=1.2, text="mix it gently")]
    translated = asyncio.run(
        generator._translate_segments_for_chinese_tts(
            segments,
            source_language="zh",
            translate_first=False,
        )
    )

    assert translated[0].text == "大家慢慢搅拌均匀"
    assert len(generator.translation_agent.prompts) == 1
    assert len(generator.translation_reviewer.prompts) == 2


def test_translate_review_accepts_natural_mixed_chinese_and_english_terms() -> None:
    generator = WhisperSubtitleGenerator()
    generator.translation_agent = _FakeAgent([])
    generator.translation_reviewer = _FakeAgent(
        [SubtitleTranslationReview(passed=True, summary="中英混用自然，可通过")]
    )

    segments = [SubtitleSegment(start=0.0, end=1.2, text="这个 app 的通知先打开")]
    translated = asyncio.run(
        generator._translate_segments_for_chinese_tts(
            segments,
            source_language="zh",
            translate_first=False,
        )
    )

    assert translated[0].text == "这个 app 的通知先打开"
    assert len(generator.translation_agent.prompts) == 0
    assert len(generator.translation_reviewer.prompts) == 1
    assert "允许少量已经融入中文表达的英文单词" in generator.translation_reviewer.prompts[0]


def test_generate_and_burn_always_writes_dedicated_tts_srt(tmp_path: Path) -> None:
    generator = WhisperSubtitleGenerator()
    generator.translation_agent = _FakeAgent(
        [_batch("现在开始慢慢搅拌均匀然后继续搅拌到完全顺滑最后再把表面的小气泡轻轻整理掉")]
    )
    generator.translation_reviewer = _FakeAgent(
        [SubtitleTranslationReview(passed=True, summary="全部通过")]
    )

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
    generator._transcribe_with_whisper = _fake_transcribe  # type: ignore[method-assign]
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
