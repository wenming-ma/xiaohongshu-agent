"""
图片生成状态管理模块

包含：
- ImageGenState: 图片生成状态
- MessageHistoryManager: 消息历史管理
"""
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai.messages import ModelMessage

from ...models.schemas import (
    ResearchResult,
    XHSContent,
    GroupSpec,
    ImageTypeSpec,
    GeneratedImage,
)


# ============================================================================
# 消息历史管理
# ============================================================================

class MessageHistoryManager:
    """管理分组和审核的消息历史"""

    def __init__(self, max_rounds: int = 3):
        """
        初始化消息历史管理器

        Args:
            max_rounds: 保留的最大轮数
        """
        self.grouping_rounds: list[list[ModelMessage]] = []
        self.review_rounds: list[list[ModelMessage]] = []
        self.max_rounds = max_rounds

    def add_grouping_round(self, messages: list[ModelMessage]) -> None:
        """添加一轮分组消息"""
        self.grouping_rounds.append(messages)

    def get_grouping_history(self) -> list[ModelMessage]:
        """获取分组消息历史（保留最近 N 轮）"""
        kept_rounds = self.grouping_rounds[-self.max_rounds:]
        return [msg for round_msgs in kept_rounds for msg in round_msgs]

    def add_review_round(self, messages: list[ModelMessage]) -> None:
        """添加一轮审核消息"""
        self.review_rounds.append(messages)

    def get_review_history(self) -> list[ModelMessage]:
        """获取审核消息历史（保留最近 N 轮）"""
        kept_rounds = self.review_rounds[-self.max_rounds:]
        return [msg for round_msgs in kept_rounds for msg in round_msgs]


# ============================================================================
# State 数据类
# ============================================================================

@dataclass
class ImageGenState:
    """图片生成运行时状态"""
    topic: str
    research: ResearchResult
    content: XHSContent
    output_dir: Path

    # 分组状态
    groups: list[GroupSpec] = field(default_factory=list)
    image_types: list[ImageTypeSpec] = field(default_factory=list)

    # 生成状态
    generated_images: list[GeneratedImage] = field(default_factory=list)

    # 消息历史
    history_manager: MessageHistoryManager = field(default_factory=MessageHistoryManager)
