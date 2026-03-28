from src.agents.video_post.utils.video_dubbing import (
    MAX_NATURAL_ATEMPO,
    MIN_NATURAL_ATEMPO,
    SrtSegment,
    _plan_concat_silence,
    _resolve_tempo_filter,
)


def test_resolve_tempo_filter_clamps_extreme_speed_changes() -> None:
    assert _resolve_tempo_filter(4.0, 2.0) == f"atempo={MAX_NATURAL_ATEMPO:.6f}"
    assert _resolve_tempo_filter(1.0, 3.0) == f"atempo={MIN_NATURAL_ATEMPO:.6f}"
    assert _resolve_tempo_filter(1.0, 1.0) == "atempo=1.000000"


def test_plan_concat_silence_preserves_original_gap_when_audio_is_shorter() -> None:
    segments = [
        (SrtSegment(index=1, start=0.0, end=2.0, text="第一句"), 1.0),
        (SrtSegment(index=2, start=4.0, end=5.0, text="第二句"), 1.0),
    ]

    silences, tail_gap = _plan_concat_silence(segments, total_duration=7.0)

    assert silences == [0.0, 3.0]
    assert tail_gap == 2.0


def test_plan_concat_silence_delays_next_segment_when_audio_overruns() -> None:
    segments = [
        (SrtSegment(index=1, start=0.0, end=2.0, text="第一句"), 3.0),
        (SrtSegment(index=2, start=2.5, end=3.5, text="第二句"), 1.0),
    ]

    silences, tail_gap = _plan_concat_silence(segments, total_duration=6.0)

    assert silences == [0.0, 0.0]
    assert tail_gap == 2.0
