import tempfile
from pathlib import Path

from src.agents.video_post.download.subtitle import SubtitleGenerator, SubtitleSegment
from src.agents.video_post.utils.tts_tags import (
    DEFAULT_TONE_TAG,
    normalize_tone_tag,
    prepare_provider_tts_text,
)
from src.agents.video_post.utils.video_dubbing import parse_srt


def test_normalize_tone_tag_accepts_short_english_phrase() -> None:
    assert normalize_tone_tag(" Friendly Tone ") == "friendly tone"


def test_normalize_tone_tag_rejects_invalid_input() -> None:
    assert normalize_tone_tag("特别开心") == DEFAULT_TONE_TAG
    assert normalize_tone_tag("way too many words here") == DEFAULT_TONE_TAG
    assert normalize_tone_tag("happy!!!") == DEFAULT_TONE_TAG


def test_prepare_provider_tts_text_strips_tag_for_google() -> None:
    assert prepare_provider_tts_text("[friendly] 大家好", provider="google") == "大家好"
    assert prepare_provider_tts_text("大家好", provider="fish", tone_tag="friendly") == "[friendly] 大家好"


def test_generate_srt_writes_display_and_tts_tracks() -> None:
    generator = SubtitleGenerator()
    segments = [
        SubtitleSegment(start=0.0, end=1.5, text="慢慢搅拌均匀", tone_tag="gentle"),
        SubtitleSegment(start=1.5, end=3.0, text="这一步很关键", tone_tag="serious"),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        display_srt = Path(temp_dir) / "display.srt"
        tts_srt = Path(temp_dir) / "tts.srt"
        generator._generate_srt(segments, display_srt, include_tone_tags=False)
        generator._generate_srt(segments, tts_srt, include_tone_tags=True)

        display_text = display_srt.read_text(encoding="utf-8")
        tts_text = tts_srt.read_text(encoding="utf-8")

        assert "[gentle]" not in display_text
        assert "[serious]" not in display_text
        assert "[gentle] 慢慢搅拌均匀" in tts_text
        assert "[serious] 这一步很关键" in tts_text


def test_parse_srt_extracts_leading_tone_tag() -> None:
    srt_content = (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "[friendly] 大家好\n\n"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        srt_path = Path(temp_dir) / "sample.srt"
        srt_path.write_text(srt_content, encoding="utf-8")
        segments = parse_srt(srt_path)

    assert len(segments) == 1
    assert segments[0].tone_tag == "friendly"
    assert segments[0].text == "大家好"
