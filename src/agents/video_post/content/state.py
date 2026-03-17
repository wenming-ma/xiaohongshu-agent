from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from ..schemas import VideoResearchResult, VideoSource, XHSVideoContent, ContentReviewResult, TranscriptionResult


@dataclass
class ContentState:
    research: VideoResearchResult
    video_source: VideoSource
    topic: str
    transcript: TranscriptionResult | None = None

    message_history: list[ModelMessage] = field(default_factory=list)
    review_history: list[ModelMessage] = field(default_factory=list)

    current_content: XHSVideoContent | None = None
    current_review: ContentReviewResult | None = None
    last_feedback: str | None = None

    def inject_feedback(self, feedback: str) -> None:
        self.last_feedback = feedback.strip()

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        history = self.message_history
        if not history or max_rounds <= 0:
            return []

        run_boundaries = [
            idx
            for idx, msg in enumerate(history)
            if isinstance(msg, ModelRequest)
            and any(isinstance(part, UserPromptPart) for part in msg.parts)
        ]

        if len(run_boundaries) <= max_rounds:
            return history

        # 始终保留首轮（包含 SystemPromptPart）+ 最近 N-1 轮
        # run_boundaries[1] 是第二轮的起始位置，即首轮的结束位置
        first_round_end = run_boundaries[1] if len(run_boundaries) > 1 else len(history)
        recent_start = run_boundaries[-(max_rounds - 1)]
        return history[:first_round_end] + history[recent_start:]

    def get_recent_review_history(self, max_rounds: int) -> list[ModelMessage]:
        history = self.review_history
        if not history or max_rounds <= 0:
            return []

        run_boundaries = [
            idx
            for idx, msg in enumerate(history)
            if isinstance(msg, ModelRequest)
            and any(isinstance(part, UserPromptPart) for part in msg.parts)
        ]

        if len(run_boundaries) <= max_rounds:
            return history

        # 始终保留首轮（包含 SystemPromptPart）+ 最近 N-1 轮
        # run_boundaries[1] 是第二轮的起始位置，即首轮的结束位置
        first_round_end = run_boundaries[1] if len(run_boundaries) > 1 else len(history)
        recent_start = run_boundaries[-(max_rounds - 1)]
        return history[:first_round_end] + history[recent_start:]
