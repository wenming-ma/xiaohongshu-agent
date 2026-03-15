"""Runtime state for article content generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart

from ..schemas import (
    ArticleResearchResult,
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
    output_dir: Path | None = None

    message_history: list[ModelMessage] = field(default_factory=list)

    current_content: XHSArticleContent | None = None
    last_feedback: str | None = None

    def inject_feedback(self, feedback: str) -> None:
        self.last_feedback = feedback
        self.message_history.append(ModelRequest(parts=[UserPromptPart(content=feedback)]))

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        return _safe_truncate(self.message_history, max_rounds * 2)


def _safe_truncate(history: list[ModelMessage], max_messages: int) -> list[ModelMessage]:
    """截取最近 N 条消息，保证不以 ToolReturnPart 开头（避免 tool_use_id 孤立）"""
    if len(history) <= max_messages:
        return history

    start_idx = len(history) - max_messages

    while start_idx > 0:
        msg = history[start_idx]
        if isinstance(msg, ModelRequest) and any(isinstance(p, ToolReturnPart) for p in msg.parts):
            start_idx -= 1
        else:
            break

    return history[start_idx:]
