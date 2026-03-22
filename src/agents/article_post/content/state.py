"""Runtime state for article content generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart

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
        """按完整 user prompt 边界截取（始终保留首轮 + 最近 N-1 轮）。

        当 max_rounds=1 时只保留首轮（包含 SystemPromptPart）；
        当 max_rounds=2 时保留首轮 + 最近 1 轮，以此类推。
        """
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

        # 始终保留首轮（包含 SystemPromptPart）
        first_round_end = run_boundaries[1] if len(run_boundaries) > 1 else len(history)

        # max_rounds=1 → 只保留首轮，不追加后续轮次
        if max_rounds <= 1:
            return history[:first_round_end]

        # max_rounds>=2 → 首轮 + 最近 (max_rounds-1) 轮
        recent_start = run_boundaries[-(max_rounds - 1)]
        return history[:first_round_end] + history[recent_start:]
