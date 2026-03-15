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

    def inject_feedback(self, feedback: str) -> None:
        self.message_history.append(ModelRequest(parts=[UserPromptPart(content=feedback)]))

    def get_recent_history(self, max_messages: int) -> list[ModelMessage]:
        return _safe_truncate(self.message_history, max_messages)


def _safe_truncate(history: list[ModelMessage], max_messages: int) -> list[ModelMessage]:
    # 过滤所有带 tool_call_id 的消息，避免 Anthropic 兼容端点在跨轮继续时
    # 收到孤立的 tool_result / retry_prompt 并报 "tool id not found"。
    filtered = [
        msg for msg in history
        if not any(getattr(part, "tool_call_id", None) for part in msg.parts)
    ]
    return filtered[-max_messages:]
