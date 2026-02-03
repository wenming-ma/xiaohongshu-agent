"""
内容创作状态管理模块

包含：
- ContentState: 内容创作运行时状态
- 消息历史处理（作为 HistoryProcessor）
- 反馈注入
"""
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart, ToolReturnPart, ToolCallPart

from ...models.schemas import ResearchResult, XHSContent, ReviewResult


# ============================================================================
# State 数据类
# ============================================================================

@dataclass
class ContentState:
    """内容创作运行时状态"""
    research: ResearchResult
    topic: str

    # 消息历史
    message_history: list[ModelMessage] = field(default_factory=list)
    review_history: list[ModelMessage] = field(default_factory=list)

    # 当前结果
    current_content: XHSContent | None = None
    current_review: ReviewResult | None = None

    # ========================================================================
    # 反馈注入
    # ========================================================================

    def inject_feedback(self, feedback: str) -> None:
        """注入审核反馈到消息历史"""
        self.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=feedback)])
        )

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        """获取最近 N 轮对话历史，确保 tool_use/tool_result 配对完整"""
        max_messages = max_rounds * 2
        if len(self.message_history) <= max_messages:
            return self.message_history

        start_idx = len(self.message_history) - max_messages

        # 确保不会截断 tool_use/tool_result 配对
        while start_idx > 0:
            msg = self.message_history[start_idx]
            if isinstance(msg, ModelRequest) and any(isinstance(p, ToolReturnPart) for p in msg.parts):
                start_idx -= 1
            else:
                break

        return self.message_history[start_idx:]


# ============================================================================
# 消息历史简化（作为 HistoryProcessor）
# ============================================================================

def simplify_content_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """
    简化消息历史，减少 token 消耗

    符合 pydantic-ai HistoryProcessor 接口：
    - 输入：list[ModelMessage]
    - 输出：list[ModelMessage]

    当前实现：简单返回原消息（后续可优化为智能简化）
    """
    # TODO: 实现智能简化（类似 ResearchAgent）
    # - 保留最后的关键消息
    # - 截断中间冗余内容
    # - 简化工具调用参数
    return messages
