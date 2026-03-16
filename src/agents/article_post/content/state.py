"""Runtime state for article content generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart

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
        self.last_feedback = feedback.strip()

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        """只保留最近 N 轮最终长文输出，不保留中间 tool call 链。"""
        history = self.message_history
        if not history or max_rounds <= 0:
            return []

        outputs: list[ModelMessage] = []
        for msg in reversed(history):
            if not isinstance(msg, ModelResponse):
                continue
            if any(isinstance(part, ToolCallPart) for part in msg.parts):
                continue
            outputs.append(msg)
            if len(outputs) >= max_rounds:
                break

        return list(reversed(outputs))
