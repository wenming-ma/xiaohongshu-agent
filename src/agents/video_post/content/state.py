from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage

from ...shared.utils.asr.schemas import TranscriptionResult
from ...shared.utils.message_history import truncate_history_by_rounds
from ..schemas import VideoResearchResult, VideoSource, XHSVideoContent, ContentReviewResult


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

    @staticmethod
    def _truncate_history(history: list[ModelMessage], max_rounds: int) -> list[ModelMessage]:
        return truncate_history_by_rounds(
            history,
            max_rounds=max_rounds,
            keep_first_round=False,
        )

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        return self._truncate_history(self.message_history, max_rounds)

    def get_recent_review_history(self, max_rounds: int) -> list[ModelMessage]:
        return self._truncate_history(self.review_history, max_rounds)
