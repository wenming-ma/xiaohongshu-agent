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

    def inject_feedback(self, feedback: str) -> None:
        self.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=feedback)])
        )
