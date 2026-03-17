"""内容创作状态管理"""
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from ..schemas import ResearchResult, XHSContent, ReviewResult, GroupSpec


@dataclass
class ContentState:
    """内容创作运行时状态"""
    research: ResearchResult
    topic: str

    groups: list[GroupSpec] | None = None

    message_history: list[ModelMessage] = field(default_factory=list)
    review_history: list[ModelMessage] = field(default_factory=list)

    current_content: XHSContent | None = None
    current_review: ReviewResult | None = None
    last_feedback: str | None = None

    def inject_feedback(self, feedback: str) -> None:
        """保存审核反馈，供下一轮修订 prompt 使用"""
        self.last_feedback = feedback.strip()

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        """按完整 user prompt 边界截取最近 N 轮对话历史（始终保留第 1 轮）。"""
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
        """按完整 user prompt 边界截取最近 N 轮审核历史（始终保留第 1 轮）。"""
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


def simplify_content_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """简化消息历史（HistoryProcessor 接口）"""
    return messages
