"""内容创作状态管理"""
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage

from ...shared.utils.message_history import truncate_history_by_rounds
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
        """按完整轮次截取最近 N 轮，并清理悬空 tool call / return。"""
        return truncate_history_by_rounds(
            self.message_history,
            max_rounds=max_rounds,
            keep_first_round=False,
        )

    def get_recent_review_history(self, max_rounds: int) -> list[ModelMessage]:
        """按完整轮次截取最近 N 轮审核历史，并清理悬空 tool call / return。"""
        return truncate_history_by_rounds(
            self.review_history,
            max_rounds=max_rounds,
            keep_first_round=False,
        )


def simplify_content_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """简化消息历史（HistoryProcessor 接口）"""
    return messages
