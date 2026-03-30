import asyncio
import os
import re
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ....utils.logger import get_logger
from ..schemas import SubtitleSegment
from .tts_tags import DEFAULT_TONE_TAG, build_tts_text, normalize_tone_tag

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants & config
# ---------------------------------------------------------------------------

SUBTITLE_CONFIG = {
    "TARGET_LANGUAGE": "zh",
    "FONT_NAME": "Microsoft YaHei",
    "FONT_SIZE": 18,
    "ENABLE_TRANSLATION": True,
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TTS_SPLIT_RE = re.compile(r"(?<=[。！？；，、：,.!?;:])\s*")
_MAX_TTS_SEGMENT_CHARS = 18
_MAX_TTS_CHARS_PER_SECOND = 5.5
_MIN_TTS_SEGMENT_DURATION = 0.35

SUBTITLE_STYLES = {
    "food": {
        "PrimaryColour": "&H0000FFFF",
        "OutlineColour": "&H00000000",
    },
    "fashion": {
        "PrimaryColour": "&H00B469FF",
        "OutlineColour": "&H00FFFFFF",
    },
    "travel": {
        "PrimaryColour": "&H00FFBF00",
        "OutlineColour": "&H00FFFFFF",
    },
    "tech": {
        "PrimaryColour": "&H00FFFF00",
        "OutlineColour": "&H00000000",
    },
    "fitness": {
        "PrimaryColour": "&H0000FF7F",
        "OutlineColour": "&H00000000",
    },
    "default": {
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
    },
}

_STYLE_KEYWORDS = {
    "food": [
        "美食", "烹饪", "做饭", "食谱", "料理", "便当", "甜点", "烘焙", "厨房", "菜",
        "food", "cook", "recipe", "bento", "kitchen", "bake", "meal", "dish", "ramen",
        "sushi", "dessert", "lunch", "dinner", "breakfast",
    ],
    "fashion": [
        "穿搭", "时尚", "美妆", "化妆", "护肤", "搭配", "衣服", "口红", "妆容",
        "fashion", "makeup", "beauty", "skincare", "outfit", "style", "cosmetic",
    ],
    "travel": [
        "旅行", "旅游", "攻略", "打卡", "探店", "城市", "酒店", "风景", "游",
        "travel", "trip", "tour", "vlog", "explore", "city", "hotel", "景",
    ],
    "tech": [
        "科技", "数码", "手机", "电脑", "测评", "开箱", "编程", "AI",
        "tech", "review", "unbox", "phone", "computer", "gadget", "code",
    ],
    "fitness": [
        "健身", "运动", "减肥", "瑜伽", "跑步", "训练", "塑形",
        "fitness", "workout", "gym", "yoga", "exercise", "training",
    ],
}

# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def normalize_subtitle_text(text: str) -> str:
    cleaned = _HTML_TAG_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _resolve_tone_tag(segment: Any) -> str:
    return normalize_tone_tag(getattr(segment, "tone_tag", "") or DEFAULT_TONE_TAG)


def _visible_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", normalize_subtitle_text(text)))


def _split_text_for_tts(text: str, max_chars: int = _MAX_TTS_SEGMENT_CHARS) -> list[str]:
    normalized = normalize_subtitle_text(text)
    if not normalized:
        return []

    chunks = [part.strip() for part in _TTS_SPLIT_RE.split(normalized) if part.strip()]
    if not chunks:
        chunks = [normalized]

    results: list[str] = []
    for chunk in chunks:
        if _visible_text_length(chunk) <= max_chars:
            results.append(chunk)
            continue

        words = chunk.split(" ")
        if len(words) > 1:
            current_words: list[str] = []
            for word in words:
                candidate = " ".join([*current_words, word]).strip()
                if current_words and _visible_text_length(candidate) > max_chars:
                    results.append(" ".join(current_words).strip())
                    current_words = [word]
                else:
                    current_words.append(word)
            if current_words:
                results.append(" ".join(current_words).strip())
            continue

        cursor = 0
        while cursor < len(chunk):
            next_cursor = min(cursor + max_chars, len(chunk))
            results.append(chunk[cursor:next_cursor].strip())
            cursor = next_cursor

    return [item for item in results if item]


def _allocate_tts_durations(parts: list[str], total_duration: float) -> list[float]:
    if not parts:
        return []

    total_duration = max(total_duration, _MIN_TTS_SEGMENT_DURATION * len(parts))

    weights = [max(_visible_text_length(part), 1) for part in parts]
    total_weight = sum(weights) or len(parts)
    durations = [total_duration * weight / total_weight for weight in weights]

    shortfall = 0.0
    for index, value in enumerate(durations):
        if value < _MIN_TTS_SEGMENT_DURATION:
            shortfall += _MIN_TTS_SEGMENT_DURATION - value
            durations[index] = _MIN_TTS_SEGMENT_DURATION

    if shortfall > 0:
        adjustable = [
            idx for idx, value in enumerate(durations)
            if value > _MIN_TTS_SEGMENT_DURATION + 1e-6
        ]
        while shortfall > 1e-6 and adjustable:
            adjustable_total = sum(
                durations[idx] - _MIN_TTS_SEGMENT_DURATION for idx in adjustable
            )
            if adjustable_total <= 1e-6:
                break
            next_adjustable: list[int] = []
            for idx in adjustable:
                available = durations[idx] - _MIN_TTS_SEGMENT_DURATION
                reduction = min(shortfall * (available / adjustable_total), available)
                durations[idx] -= reduction
                shortfall -= reduction
                if durations[idx] > _MIN_TTS_SEGMENT_DURATION + 1e-6:
                    next_adjustable.append(idx)
            adjustable = next_adjustable

    return durations


def pick_subtitle_style(topic: str) -> dict:
    topic_lower = topic.lower()
    for style_name, keywords in _STYLE_KEYWORDS.items():
        if any(keyword in topic_lower for keyword in keywords):
            logger.info(f"字幕配色: {style_name}")
            return SUBTITLE_STYLES[style_name]
    logger.info("字幕配色: default")
    return SUBTITLE_STYLES["default"]


# ---------------------------------------------------------------------------
# Functions extracted from SubtitleGenerator class methods
# ---------------------------------------------------------------------------


def build_tts_segments(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    tts_segments: list[SubtitleSegment] = []
    cursor = 0.0

    for segment in segments:
        text = normalize_subtitle_text(segment.text)
        if not text:
            continue

        duration = max(segment.end - segment.start, 0.0)
        density = (_visible_text_length(text) / duration) if duration > 1e-6 else float("inf")
        parts = _split_text_for_tts(text)
        should_split = (
            len(parts) > 1
            or _visible_text_length(text) > _MAX_TTS_SEGMENT_CHARS
            or density > _MAX_TTS_CHARS_PER_SECOND
        )
        effective_parts = parts if should_split else [text]
        part_durations = _allocate_tts_durations(effective_parts, duration)

        part_cursor = max(segment.start, cursor)
        for part, part_duration in zip(effective_parts, part_durations):
            start = part_cursor
            end = start + part_duration
            tts_segments.append(
                SubtitleSegment(
                    start=start,
                    end=end,
                    text=part,
                    speaker_id=segment.speaker_id,
                    tone_tag=_resolve_tone_tag(segment),
                )
            )
            part_cursor = end

        cursor = part_cursor

    return tts_segments


def generate_srt(
    segments: list[SubtitleSegment],
    output_path: Path,
    *,
    include_tone_tags: bool,
) -> None:
    has_speakers = any(segment.speaker_id != 0 for segment in segments)
    with open(output_path, "w", encoding="utf-8") as handle:
        for index, segment in enumerate(segments, 1):
            start = format_srt_timestamp(segment.start)
            end = format_srt_timestamp(segment.end)
            text = segment.text
            if include_tone_tags:
                text = build_tts_text(text, _resolve_tone_tag(segment))
            if has_speakers:
                text = f"[S{segment.speaker_id}] {text}"
            handle.write(f"{index}\n{start} --> {end}\n{text}\n\n")


def format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


async def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    *,
    topic: str = "",
    font_name: str = "",
    font_path: Path | None = None,
) -> None:
    style = pick_subtitle_style(topic)
    resolved_font_name = font_name or SUBTITLE_CONFIG["FONT_NAME"]

    tmp_dir = Path(tempfile.mkdtemp(prefix="subs_"))
    try:
        shutil.copy2(srt_path, tmp_dir / "sub.srt")
        env = None
        if font_path and font_path.exists():
            shutil.copy2(font_path, tmp_dir / font_path.name)
            fonts_conf = tmp_dir / "fonts.conf"
            fonts_conf.write_text(
                f'<?xml version="1.0"?>\n<fontconfig><dir>{tmp_dir}</dir></fontconfig>\n',
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["FONTCONFIG_FILE"] = str(fonts_conf)

        subtitle_filter = (
            "subtitles=sub.srt:force_style="
            f"'FontName={resolved_font_name},"
            f"FontSize={SUBTITLE_CONFIG['FONT_SIZE']},"
            f"Bold=1,"
            f"PrimaryColour={style['PrimaryColour']},"
            f"OutlineColour={style['OutlineColour']},"
            "BackColour=&H80000000,"
            "Outline=2,"
            "Shadow=1,"
            "BorderStyle=1,"
            "MarginV=30'"
        )
        cmd = [
            "ffmpeg",
            "-hwaccel",
            "cuda",
            "-i",
            str(video_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-cq",
            "20",
            "-c:a",
            "copy",
            "-y",
            str(output_path),
        ]

        logger.info(f"开始烧录字幕到视频（字体: {resolved_font_name}）...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(tmp_dir),
            env=env,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg 字幕烧录失败: {stderr.decode()[-500:]}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("烧录后的视频文件为空")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
