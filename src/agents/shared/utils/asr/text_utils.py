from __future__ import annotations

import re
from dataclasses import dataclass

from src.agents.video_post.schemas import SubtitleSegment, TranscriptionResult

NO_SPACE_LANGUAGES = {"zh", "ja", "ko"}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def visible_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", normalize_text(text)))


def join_segments_to_transcript(segments: list[SubtitleSegment], language: str) -> str:
    parts = [normalize_text(segment.text) for segment in segments if normalize_text(segment.text)]
    if not parts:
        return ""
    separator = "" if (language or "").lower() in NO_SPACE_LANGUAGES else " "
    return separator.join(parts).strip()


def split_transcript_units(text: str, language: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    if (language or "").lower() in NO_SPACE_LANGUAGES:
        return [char for char in normalized if not char.isspace()]

    words = normalized.split()
    return words or [normalized]


def join_transcript_units(units: list[str], language: str) -> str:
    separator = "" if (language or "").lower() in NO_SPACE_LANGUAGES else " "
    return separator.join(units).strip()


def allocate_units(total_units: int, weights: list[float]) -> list[int]:
    if not weights:
        return []
    if total_units <= 0:
        return [0] * len(weights)
    if total_units < len(weights):
        raise ValueError("total_units must be >= number of weights")

    counts = [1] * len(weights)
    remaining = total_units - len(weights)
    if remaining <= 0:
        return counts

    normalized_weights = [max(weight, 1.0) for weight in weights]
    total_weight = sum(normalized_weights) or float(len(normalized_weights))
    raw_allocations = [remaining * weight / total_weight for weight in normalized_weights]
    base_allocations = [int(value) for value in raw_allocations]
    counts = [count + base for count, base in zip(counts, base_allocations)]
    leftover = total_units - sum(counts)
    if leftover <= 0:
        return counts

    order = sorted(
        range(len(weights)),
        key=lambda index: raw_allocations[index] - base_allocations[index],
        reverse=True,
    )
    for index in range(leftover):
        counts[order[index % len(order)]] += 1
    return counts


def build_transcription_result(
    *,
    language: str,
    segments: list[SubtitleSegment],
    transcript: str = "",
    duration_seconds: int = 0,
) -> TranscriptionResult:
    cleaned_segments = []
    for segment in segments:
        text = normalize_text(segment.text)
        if not text:
            continue
        cleaned_segments.append(
            SubtitleSegment(
                start=float(segment.start),
                end=max(float(segment.end), float(segment.start) + 0.01),
                text=text,
                speaker_id=getattr(segment, "speaker_id", 0),
                tone_tag=getattr(segment, "tone_tag", ""),
            )
        )

    resolved_language = (language or "").strip()
    resolved_transcript = (
        join_segments_to_transcript(cleaned_segments, resolved_language)
        if cleaned_segments
        else normalize_text(transcript)
    )
    resolved_duration = duration_seconds
    if cleaned_segments:
        resolved_duration = max(duration_seconds, int(round(cleaned_segments[-1].end)))

    return TranscriptionResult(
        success=True,
        transcript=resolved_transcript,
        language=resolved_language,
        duration_seconds=resolved_duration,
        segments=cleaned_segments,
    )


def empty_success_result(language: str = "", duration_seconds: int = 0) -> TranscriptionResult:
    return TranscriptionResult(
        success=True,
        transcript="",
        language=language,
        duration_seconds=duration_seconds,
        segments=[],
    )


def ensure_timestamped_transcription_result(result: TranscriptionResult) -> TranscriptionResult:
    if not result.success:
        return result

    if result.segments:
        return build_transcription_result(
            language=result.language,
            segments=result.segments,
            transcript=result.transcript,
            duration_seconds=result.duration_seconds,
        )

    normalized_transcript = normalize_text(result.transcript)
    if normalized_transcript:
        return build_transcription_result(
            language=result.language,
            segments=[
                SubtitleSegment(
                    start=0.0,
                    end=max(float(result.duration_seconds), 0.01),
                    text=normalized_transcript,
                )
            ],
            transcript=normalized_transcript,
            duration_seconds=result.duration_seconds,
        )

    return empty_success_result(
        language=result.language,
        duration_seconds=result.duration_seconds,
    )


@dataclass(frozen=True)
class ReferenceSpan:
    start: float
    end: float
    weight: float
