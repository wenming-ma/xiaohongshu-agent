from __future__ import annotations

from pathlib import Path

from ..providers.base import AsrProvider
from ..text_utils import (
    ReferenceSpan,
    allocate_units,
    join_transcript_units,
    normalize_text,
    split_transcript_units,
    visible_text_length,
)
from ..types import TranscriptionSegment
from .base import AlignmentResult, TimestampAligner


def _build_reference_spans(
    reference_segments: list[TranscriptionSegment],
    span_count: int,
) -> list[ReferenceSpan]:
    if span_count <= 0 or not reference_segments:
        return []

    total_segments = len(reference_segments)
    spans: list[ReferenceSpan] = []
    for index in range(span_count):
        start_index = (index * total_segments) // span_count
        end_index = ((index + 1) * total_segments) // span_count
        group = reference_segments[start_index:max(end_index, start_index + 1)]
        start = float(group[0].start)
        end = float(group[-1].end)
        weight = float(sum(max(visible_text_length(segment.text), 1) for segment in group))
        spans.append(ReferenceSpan(start=start, end=max(end, start + 0.01), weight=max(weight, 1.0)))
    return spans


def redistribute_transcript_to_segments(
    transcript: str,
    reference_segments: list[TranscriptionSegment],
    language: str,
) -> list[TranscriptionSegment]:
    normalized = normalize_text(transcript)
    if not normalized or not reference_segments:
        return []

    units = split_transcript_units(normalized, language)
    if not units:
        return []

    span_count = min(len(reference_segments), len(units))
    spans = _build_reference_spans(reference_segments, span_count)
    counts = allocate_units(len(units), [span.weight for span in spans])

    segments: list[TranscriptionSegment] = []
    cursor = 0
    for index, span in enumerate(spans):
        count = counts[index]
        part_units = units[cursor:cursor + count]
        cursor += count
        text = join_transcript_units(part_units, language)
        if not text:
            continue
        segments.append(
            TranscriptionSegment(
                start=span.start,
                end=span.end,
                text=text,
            )
        )

    if cursor < len(units) and segments:
        tail = join_transcript_units(units[cursor:], language)
        if tail:
            separator = "" if (language or "").lower() in {"zh", "ja", "ko"} else " "
            segments[-1].text = f"{segments[-1].text}{separator}{tail}".strip()

    return segments


class ReferenceSegmentAligner(TimestampAligner):
    aligner_name = "reference_segments"

    def __init__(self, reference_provider: AsrProvider):
        self._reference_provider = reference_provider

    def align(
        self,
        *,
        audio_path: Path,
        transcript: str,
        language: str,
    ) -> AlignmentResult:
        reference_result = self._reference_provider.transcribe_audio(audio_path)
        if not reference_result.success:
            raise RuntimeError(reference_result.error_message or "参考时间戳生成失败")

        resolved_language = (language or reference_result.language or "").strip()
        resolved_duration = reference_result.duration_seconds
        if reference_result.segments:
            resolved_duration = max(
                resolved_duration,
                int(round(reference_result.segments[-1].end)),
            )

        segments = redistribute_transcript_to_segments(
            transcript,
            reference_result.segments,
            resolved_language,
        )
        if not segments and normalize_text(transcript):
            segments = [
                TranscriptionSegment(
                    start=0.0,
                    end=max(float(resolved_duration), 0.01),
                    text=normalize_text(transcript),
                )
            ]

        return AlignmentResult(
            segments=segments,
            duration_seconds=resolved_duration,
            language=resolved_language,
        )

    def release(self) -> None:
        self._reference_provider.release()
