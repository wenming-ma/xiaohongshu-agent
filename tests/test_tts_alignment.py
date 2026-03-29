import asyncio
from pathlib import Path

from src.agents.video_post.utils.tts_alignment import (
    BoundaryAwareTtsAligner,
    TtsSynthesisRequest,
    TtsSynthesisResult,
)


def test_boundary_fallback_aligner_generates_monotonic_tokens() -> None:
    aligner = BoundaryAwareTtsAligner()
    synthesis = TtsSynthesisResult(
        audio_path=Path("segment.wav"),
        raw_duration_seconds=2.4,
        provider_name="fish",
    )
    request = TtsSynthesisRequest(
        text="先把鸡蛋打散，然后轻轻地下锅。",
        target_duration_seconds=2.0,
    )

    aligned = asyncio.run(aligner.align(synthesis, request))
    tokens = aligned.tokens

    assert tokens
    assert aligned.aligner_used == "boundary_fallback"
    assert tokens[0].start == 0.0
    assert tokens[-1].end == 2.4
    assert all(item.end >= item.start for item in tokens)
    assert all(
        tokens[index].start >= tokens[index - 1].end
        for index in range(1, len(tokens))
    )
