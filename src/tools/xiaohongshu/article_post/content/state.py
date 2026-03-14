"""Runtime state for article content generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart

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
    output_dir: Path | None = None

    message_history: list[ModelMessage] = field(default_factory=list)

    current_content: XHSArticleContent | None = None

    def inject_feedback(self, feedback: str) -> None:
        self.message_history.append(ModelRequest(parts=[UserPromptPart(content=feedback)]))

    def get_recent_history(self, max_messages: int) -> list[ModelMessage]:
        return _safe_truncate(self.message_history, max_messages)


def _safe_truncate(history: list[ModelMessage], max_messages: int) -> list[ModelMessage]:
    # 过滤掉 tool 相关消息：跨 agent.run() 调用传递 tool 历史会导致部分模型（如 MiniMax）
    # 找不到对应的 tool_call_id 而报 400 错误
    filtered = [
        msg for msg in history
        if not (isinstance(msg, ModelRequest) and any(isinstance(p, ToolReturnPart) for p in msg.parts))
        and not (isinstance(msg, ModelResponse) and any(isinstance(p, ToolCallPart) for p in msg.parts))
    ]
    return filtered[-max_messages:]
