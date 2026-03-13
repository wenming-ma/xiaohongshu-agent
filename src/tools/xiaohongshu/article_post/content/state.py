"""Runtime state for article content generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart

from ..schemas import (
    ArticleResearchResult,
    ArticleReviewResult,
    ArticleStrategy,
    XHSArticleContent,
)


@dataclass
class ContentState:
    research: ArticleResearchResult
    topic: str
    target_audience: str
    strategy: ArticleStrategy
    generate_images: bool

    message_history: list[ModelMessage] = field(default_factory=list)
    review_history: list[ModelMessage] = field(default_factory=list)

    current_content: XHSArticleContent | None = None
    current_review: ArticleReviewResult | None = None

    def inject_feedback(self, feedback: str) -> None:
        self.message_history.append(ModelRequest(parts=[UserPromptPart(content=feedback)]))

    def get_recent_history(self, max_messages: int) -> list[ModelMessage]:
        return _safe_truncate(self.message_history, max_messages)

    def get_recent_review_history(self, max_messages: int) -> list[ModelMessage]:
        return _safe_truncate(self.review_history, max_messages)


def _safe_truncate(history: list[ModelMessage], max_messages: int) -> list[ModelMessage]:
    if len(history) <= max_messages:
        return history

    start_idx = len(history) - max_messages
    while start_idx > 0:
        msg = history[start_idx]
        if isinstance(msg, ModelRequest) and any(isinstance(part, ToolReturnPart) for part in msg.parts):
            start_idx -= 1
            continue
        break
    return history[start_idx:]
