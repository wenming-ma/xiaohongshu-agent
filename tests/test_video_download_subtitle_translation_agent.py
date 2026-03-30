import asyncio
from types import SimpleNamespace

from pydantic_ai import ModelRetry

from src.agents.video_post.schemas import SubtitleSegment
from src.agents.video_post.download.agent import DownloadAgent
from src.agents.video_post.download.subtitle_translation_agent import (
    SubtitleTranslationAgent,
    SubtitleTranslationReview,
    TranslationBatch,
    TranslationLine,
)


class _FakeRunner:
    def __init__(self, outputs: list[object]):
        self.outputs = list(outputs)
        self.calls: list[str] = []

    async def run(self, prompt: str, **_: object):
        self.calls.append(prompt)
        if not self.outputs:
            raise AssertionError("unexpected agent call")
        return SimpleNamespace(
            output=self.outputs.pop(0),
            new_messages=lambda: [],
        )


class _FakeBatchTranslationAgent:
    def __init__(self):
        self.calls: list[tuple[int, str, bool]] = []

    async def forward(
        self,
        segments: list[SubtitleSegment],
        *,
        source_language: str,
        translate_first: bool = True,
    ) -> list[SubtitleSegment]:
        self.calls.append((len(segments), source_language, translate_first))
        return segments


def _build_agent(
    monkeypatch,
    *,
    translator_outputs: list[TranslationBatch],
    reviewer_outputs: list[SubtitleTranslationReview],
    max_review_rounds: int = 10,
) -> SubtitleTranslationAgent:
    def _init_agent(self) -> None:
        self.translator = _FakeRunner(translator_outputs)
        self.reviewer = _FakeRunner(reviewer_outputs)

    monkeypatch.setattr(SubtitleTranslationAgent, "init_agent", _init_agent)
    return SubtitleTranslationAgent(max_review_rounds=max_review_rounds)


def _get_output_validator() -> object:
    agent = SubtitleTranslationAgent(max_review_rounds=1)
    return agent.translator._output_validators[0]


def test_subtitle_translation_agent_revises_until_review_passes(monkeypatch) -> None:
    agent = _build_agent(
        monkeypatch,
        translator_outputs=[
            TranslationBatch(lines=[TranslationLine(index=1, tone_tag="neutral", text="Pasta")]),
            TranslationBatch(lines=[TranslationLine(index=1, tone_tag="friendly", text="意面")]),
        ],
        reviewer_outputs=[
            SubtitleTranslationReview(
                passed=False,
                summary="有外语残留",
                issues=["第1行的 Pasta 需要改成中文表达"],
            ),
            SubtitleTranslationReview(passed=True, summary="审核通过"),
        ],
    )

    result = asyncio.run(
        agent.forward(
            [SubtitleSegment(start=0.0, end=1.0, text="Pasta", tone_tag="neutral")],
            source_language="en",
            translate_first=True,
        )
    )

    assert [segment.text for segment in result] == ["意面"]
    assert result[0].tone_tag == "friendly"
    assert len(agent.translator.calls) == 2
    assert len(agent.reviewer.calls) == 2


def test_subtitle_translation_agent_raises_after_ten_failed_reviews(monkeypatch) -> None:
    agent = _build_agent(
        monkeypatch,
        translator_outputs=[
            TranslationBatch(lines=[TranslationLine(index=1, tone_tag="neutral", text="Pasta")])
            for _ in range(10)
        ],
        reviewer_outputs=[
            SubtitleTranslationReview(
                passed=False,
                summary="仍有外语残留",
                issues=["第1行必须改成自然中文"],
            )
            for _ in range(10)
        ],
        max_review_rounds=10,
    )

    try:
        asyncio.run(
            agent.forward(
                [SubtitleSegment(start=0.0, end=1.0, text="Pasta", tone_tag="neutral")],
                source_language="en",
                translate_first=True,
            )
        )
        raise AssertionError("expected subtitle translation review loop to fail")
    except RuntimeError as exc:
        assert "最大审核轮数 (10)" in str(exc)

    assert len(agent.translator.calls) == 10
    assert len(agent.reviewer.calls) == 10


def test_subtitle_translation_output_validator_rejects_duplicate_or_missing_indices() -> None:
    validator = _get_output_validator()
    translation_batch = TranslationBatch(
        lines=[
            TranslationLine(index=1, tone_tag="neutral", text="new 1"),
            TranslationLine(index=2, tone_tag="neutral", text="new 2"),
            TranslationLine(index=2, tone_tag="neutral", text="new 3"),
        ]
    )

    try:
        asyncio.run(validator.function(SimpleNamespace(deps=3), translation_batch))
        raise AssertionError("expected duplicate/missing indices to be rejected")
    except ModelRetry as exc:
        assert "index" in str(exc)


def test_subtitle_translation_output_validator_accepts_complete_contiguous_indices() -> None:
    validator = _get_output_validator()
    translation_batch = TranslationBatch(
        lines=[
            TranslationLine(index=index, tone_tag="neutral", text=f"new {index}")
            for index in range(1, 4)
        ]
    )

    result = asyncio.run(validator.function(SimpleNamespace(deps=3), translation_batch))

    assert result == translation_batch


def test_subtitle_translation_agent_raises_if_missing_index_reaches_segment_builder(monkeypatch) -> None:
    monkeypatch.setattr(SubtitleTranslationAgent, "init_agent", lambda self: None)
    agent = SubtitleTranslationAgent(max_review_rounds=1)
    source_segments = [
        SubtitleSegment(start=float(index), end=float(index + 1), text=f"source {index}", tone_tag="neutral")
        for index in range(1, 4)
    ]
    translation_batch = TranslationBatch(
        lines=[
            TranslationLine(index=1, tone_tag="neutral", text="new 1"),
            TranslationLine(index=2, tone_tag="neutral", text="new 2"),
        ]
    )

    try:
        agent._build_segments_from_result(
            source_segments=source_segments,
            translation_batch=translation_batch,
        )
        raise AssertionError("expected missing index to raise")
    except RuntimeError as exc:
        assert "缺少第 3 行" in str(exc)


def test_download_agent_keeps_batching_outside_translation_agent(monkeypatch) -> None:
    translation_agent = _FakeBatchTranslationAgent()
    monkeypatch.setattr(DownloadAgent, "init_agent", lambda self: None)
    agent = DownloadAgent.__new__(DownloadAgent)
    agent.subtitle_translation_agent = translation_agent
    segments = [
        SubtitleSegment(start=float(index), end=float(index + 1), text=f"line {index}", tone_tag="neutral")
        for index in range(16)
    ]

    result = asyncio.run(
        agent._translate_segments_for_chinese_tts(
            segments,
            source_language="en",
            translate_first=True,
        )
    )

    assert len(result) == 16
    assert len(translation_agent.calls) == 2
    assert sorted(call[0] for call in translation_agent.calls) == [1, 15]
    assert all(call[1] == "en" for call in translation_agent.calls)
    assert all(call[2] is True for call in translation_agent.calls)
