"""内容创作状态管理"""
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart, ToolReturnPart

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

    def inject_feedback(self, feedback: str) -> None:
        """注入审核反馈到消息历史"""
        self.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=feedback)])
        )

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        """获取最近 N 轮对话历史，确保 tool_use/tool_result 配对完整"""
        return _safe_truncate(self.message_history, max_rounds * 2)

    def get_recent_review_history(self, max_rounds: int) -> list[ModelMessage]:
        """获取最近 N 轮审核历史，确保 tool_use/tool_result 配对完整"""
        return _safe_truncate(self.review_history, max_rounds * 2)


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


def simplify_content_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """简化消息历史（HistoryProcessor 接口）"""
    return messages
