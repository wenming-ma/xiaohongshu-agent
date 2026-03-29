import asyncio

import pydantic_ai

import src.agents.video_post.download.agent as download_agent_module
from src.agents.shared.utils.asr.schemas import TranscriptionResult
from src.agents.video_post.download.agent import DownloadAgent
from src.agents.video_post.schemas import (
    DownloadResult,
    EngagementMetrics,
    Platform,
    VideoSource,
)
import src.utils.providers as providers


def _build_result(
    *,
    title: str,
    likes: int,
    comments: int,
    views: int,
    duration_seconds: int,
    transcript: str | None,
    language: str = "en",
) -> DownloadResult:
    source = VideoSource(
        url=f"https://example.com/{title.replace(' ', '-')}",
        platform=Platform.TIKTOK,
        title=title,
        description=title,
        duration_seconds=duration_seconds,
        video_width=1080,
        video_height=1920,
        engagement=EngagementMetrics(likes=likes, comments=comments, views=views),
    )
    transcription = None
    if transcript is not None:
        transcription = TranscriptionResult(
            success=True,
            transcript=transcript,
            language=language,
        )
    return DownloadResult(
        success=True,
        source=source,
        local_path=f"/tmp/{title}.mp4",
        file_size_bytes=50 * 1024 * 1024,
        format="mp4",
        transcription=transcription,
    )


def test_score_video_does_not_add_language_bonus_for_empty_transcript() -> None:
    agent = DownloadAgent()
    empty_transcript = _build_result(
        title="empty transcript",
        likes=2000,
        comments=200,
        views=20000,
        duration_seconds=120,
        transcript="   ",
        language="zh",
    )
    missing_transcript = _build_result(
        title="missing transcript",
        likes=2000,
        comments=200,
        views=20000,
        duration_seconds=120,
        transcript=None,
    )

    assert agent._score_video(empty_transcript, topic="dinner") == agent._score_video(
        missing_transcript,
        topic="dinner",
    )


def test_pick_best_soft_preference_can_promote_dubbable_candidate(monkeypatch) -> None:
    class _FailingAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *_args, **_kwargs):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(pydantic_ai, "Agent", _FailingAgent)
    monkeypatch.setattr(download_agent_module, "Agent", _FailingAgent)
    monkeypatch.setattr(providers, "get_text_model", lambda: "fake-model")
    monkeypatch.setattr(download_agent_module, "get_text_model", lambda: "fake-model")

    agent = DownloadAgent()
    non_dubbable_slightly_higher_base = _build_result(
        title="slightly higher base no transcript",
        likes=900000,
        comments=100000,
        views=10000000,
        duration_seconds=180,
        transcript=None,
    )
    dubbable_slightly_lower_base = _build_result(
        title="slightly lower base with transcript",
        likes=100000,
        comments=10000,
        views=1000000,
        duration_seconds=180,
        transcript="word " * 220,
    )

    best = asyncio.run(
        agent._pick_best(
            [non_dubbable_slightly_higher_base, dubbable_slightly_lower_base],
            topic="solo dinner recipe",
        )
    )

    assert best is dubbable_slightly_lower_base


def test_pick_best_soft_preference_is_not_hard_constraint(monkeypatch) -> None:
    class _FailingAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *_args, **_kwargs):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(pydantic_ai, "Agent", _FailingAgent)
    monkeypatch.setattr(download_agent_module, "Agent", _FailingAgent)
    monkeypatch.setattr(providers, "get_text_model", lambda: "fake-model")
    monkeypatch.setattr(download_agent_module, "get_text_model", lambda: "fake-model")

    agent = DownloadAgent()
    clearly_better_no_transcript = _build_result(
        title="clearly better no transcript",
        likes=500000,
        comments=50000,
        views=7000000,
        duration_seconds=180,
        transcript=None,
    )
    much_weaker_with_transcript = _build_result(
        title="much weaker with transcript",
        likes=100,
        comments=10,
        views=5000,
        duration_seconds=30,
        transcript="short transcript " * 10,
    )

    best = asyncio.run(
        agent._pick_best(
            [much_weaker_with_transcript, clearly_better_no_transcript],
            topic="solo dinner recipe",
        )
    )

    assert best is clearly_better_no_transcript
