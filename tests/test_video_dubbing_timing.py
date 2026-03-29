from src.agents.video_post.utils.video_dubbing import (
    MAX_NATURAL_ATEMPO,
    MAX_SOFT_STRETCH_RATIO,
    MIN_NATURAL_ATEMPO,
    MIN_SOFT_STRETCH_RATIO,
    SrtSegment,
    _build_timing_decision,
    _plan_concat_silence,
    _resolve_carryover_limit,
    _resolve_tempo_filter,
    _resolve_time_stretch_filter,
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


def test_resolve_carryover_limit_caps_at_small_overrun_window() -> None:
    assert _resolve_carryover_limit(2.0) == 0.16
    assert _resolve_carryover_limit(10.0) == 0.3


def test_build_timing_decision_prefers_carryover_before_stretch() -> None:
    decision = _build_timing_decision(current_seconds=2.12, target_seconds=2.0)

    assert decision.strategy_used == "carryover"
    assert decision.stretch_ratio == 1.0
    assert round(decision.carryover_seconds, 3) == 0.12


def test_build_timing_decision_only_stretches_within_soft_window() -> None:
    decision = _build_timing_decision(
        current_seconds=11.32,
        target_seconds=11.0,
    )

    assert decision.strategy_used == "stretch"
    assert MIN_SOFT_STRETCH_RATIO <= decision.stretch_ratio <= MAX_SOFT_STRETCH_RATIO


def test_build_timing_decision_keeps_large_overrun_natural() -> None:
    decision = _build_timing_decision(current_seconds=1.2, target_seconds=1.0)

    assert decision.strategy_used == "carryover_hard"
    assert decision.stretch_ratio == 1.0
    assert decision.used_fallback is True


def test_resolve_time_stretch_filter_prefers_rubberband_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.video_post.utils.video_dubbing._ffmpeg_supports_rubberband",
        lambda: True,
    )

    filter_text, strategy = _resolve_time_stretch_filter(1.02, 1.0)

    assert strategy == "rubberband"
    assert filter_text is not None
    assert filter_text.startswith("rubberband=")
