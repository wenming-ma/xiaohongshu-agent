"""Runtime state for article content generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

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
        return _safe_truncate(self.message_history, max_rounds)


def _safe_truncate(history: list[ModelMessage], max_rounds: int) -> list[ModelMessage]:
    """按完整 user prompt 边界截取最近 N 轮对话，保留整轮 tool call 链。"""
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

    start_idx = run_boundaries[-max_rounds]
    return history[start_idx:]
