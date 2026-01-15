"""
研究状态管理模块

包含：
- ResearchState: 研究运行时状态
- 进度快照构建
- 消息历史简化（作为 HistoryProcessor）
- 反馈注入
"""
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from pydantic_ai.messages import (
    ModelMessage, ModelRequest, ModelResponse,
    UserPromptPart, ToolReturnPart, TextPart, ToolCallPart, ThinkingPart
)

from ...models.schemas import ResearchResult


# ============================================================================
# State 数据类
# ============================================================================

@dataclass
class ResearchState:
    """研究运行时状态（类似 hidden state）"""
    topic: str
    target_audience: str
    output_dir: Path | None

    # 消息历史
    message_history: list[ModelMessage] = field(default_factory=list)

    # 迭代结果
    iteration_results: list[ResearchResult] = field(default_factory=list)
    saved_files: list[str] = field(default_factory=list)

    # 追踪状态
    last_progress_snapshot: str | None = None
    tracked_stats: dict = field(default_factory=dict)

    # 当前结果
    current_result: ResearchResult | None = None

    # ========================================================================
    # 反馈注入
    # ========================================================================

    def inject_feedback(self, feedback: str) -> None:
        """注入验证反馈到消息历史"""
        self.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=feedback)])
        )

    def inject_progress_snapshot(self, snapshot: str) -> None:
        """注入进度快照（如果有变化）"""
        if snapshot and snapshot != self.last_progress_snapshot:
            self.message_history.append(
                ModelRequest(parts=[UserPromptPart(content=snapshot)])
            )
            self.last_progress_snapshot = snapshot


# ============================================================================
# 进度快照构建
# ============================================================================

def _merge_iteration_data(iteration_results: list[ResearchResult]) -> tuple[list, set[str]]:
    """合并并去重迭代结果中的数据"""
    seen_items: set[str] = set()
    seen_keywords: set[str] = set()
    merged_items: list = []

    for res in iteration_results:
        for item in res.items:
            # 使用 title + content 作为唯一标识
            if hasattr(item, 'title'):
                key = f"{item.title}|{item.content}"
            else:
                key = f"{item.get('title', '')}|{item.get('content', '')}"
            if key not in seen_items:
                seen_items.add(key)
                merged_items.append(item)

        for kw in res.keywords:
            if kw:
                seen_keywords.add(str(kw))

    return merged_items, seen_keywords


def build_progress_snapshot(state: ResearchState, saved_file: str, max_items: int = 10) -> str:
    """构建进度快照，用于注入到消息历史"""
    if not state.iteration_results:
        return ""

    # 合并去重
    merged_items, seen_keywords = _merge_iteration_data(state.iteration_results)

    def _short(obj: Any, limit: int = 120) -> str:
        if hasattr(obj, 'title'):
            s = f"{obj.title}: {obj.content}"
        elif isinstance(obj, dict):
            s = f"{obj.get('title', '')}: {obj.get('content', '')}"
        else:
            s = str(obj)
        return s if len(s) <= limit else s[:limit - 12] + "...[truncated]"

    items_preview = "\n".join(f"- {_short(item)}" for item in merged_items[:max_items]) or "- (none)"
    keywords_preview = ", ".join(sorted(seen_keywords)) or "(none)"

    tracked_urls = state.tracked_stats.get("post_detail_urls") or []
    tracked_urls_preview = "\n".join(f"- {u}" for u in tracked_urls[-max_items:]) if tracked_urls else "- (none)"

    saved_files = state.saved_files[:]
    if saved_file and saved_file not in saved_files:
        saved_files.append(saved_file)

    if len(saved_files) > max_items:
        saved_files_preview = "\n".join(f"- {p}" for p in saved_files[-max_items:])
        saved_files_note = f"(total {len(saved_files)} files, showing last {max_items})"
    else:
        saved_files_preview = "\n".join(f"- {p}" for p in saved_files) or "- (none)"
        saved_files_note = ""

    return (
        f"【进度快照｜仅供参考，请勿在输出中重复】\n"
        f"- topic: {state.topic}\n"
        f"- tracked_post_count: {state.tracked_stats.get('post_detail_count', 0)}\n"
        f"- saved_json:\n{saved_files_preview}\n"
        f"{(saved_files_note + chr(10)) if saved_files_note else ''}\n"
        f"已保存的内容项（示例，最多{max_items}条）：\n{items_preview}\n\n"
        f"已保存的关键词： {keywords_preview}\n\n"
        f"已进入的帖子详情页（最近{max_items}个）：\n{tracked_urls_preview}\n\n"
        f"⚠️ 重要提醒：\n"
        f"- 以上历史数据已自动保存到文件，系统会自动合并所有轮次\n"
        f"- 本轮你只需输出【新收集】的数据，不要重复输出历史数据\n"
        f"- 请继续探索新帖子，收集新的内容项"
    )


def combine_feedback(depth_result, review_result) -> str:
    """合并验证器反馈"""
    feedbacks = []
    if not depth_result.passed and depth_result.feedback:
        feedbacks.append(depth_result.feedback)
    if not review_result.passed and review_result.feedback:
        feedbacks.append(review_result.feedback)

    combined = "\n\n---\n\n".join(feedbacks)

    return (
        f"**验证未通过，请继续探索**\n\n"
        f"{combined}\n\n"
        f"**重要提醒**：\n"
        f"- 上一轮收集的数据已自动保存，系统会自动合并所有轮次结果\n"
        f"- 本轮你只需输出【本轮新收集】的内容项\n"
        f"- 不要在输出中重复之前轮次已收集的内容\n\n"
        f"**请基于已搜索的内容发散思维，尝试不同关键词组合和细分角度，进入更多帖子详情页收集【新的】数据。**"
    )


# ============================================================================
# 消息历史简化（作为 HistoryProcessor）
# ============================================================================

def _find_last_positions(messages: list[ModelMessage]) -> dict[str, tuple[int, int] | None]:
    """找到最后一个 ToolReturn、ToolCall、Thinking 的位置"""
    positions = {
        "tool_return": None,
        "tool_call": None,
        "thinking": None,
    }

    for msg_idx, msg in enumerate(messages):
        if isinstance(msg, ModelRequest):
            for part_idx, part in enumerate(msg.parts):
                if isinstance(part, ToolReturnPart):
                    positions["tool_return"] = (msg_idx, part_idx)

        elif isinstance(msg, ModelResponse):
            for part_idx, part in enumerate(msg.parts):
                if isinstance(part, ToolCallPart):
                    positions["tool_call"] = (msg_idx, part_idx)
                elif isinstance(part, ThinkingPart):
                    positions["thinking"] = (msg_idx, part_idx)

    return positions


def _simplify_tool_request(
    msg: ModelRequest,
    msg_idx: int,
    last_positions: dict,
    summary_text: str
) -> ModelRequest:
    """简化 ModelRequest 中的 ToolReturnPart（截断非最新的工具返回）"""
    new_parts = []
    for part_idx, part in enumerate(msg.parts):
        if isinstance(part, ToolReturnPart):
            is_last = (msg_idx, part_idx) == last_positions["tool_return"]
            if is_last:
                new_parts.append(part)
            else:
                simplified_content = _truncate_content(part.content, summary_text)
                new_parts.append(ToolReturnPart(
                    tool_name=part.tool_name,
                    tool_call_id=part.tool_call_id,
                    content=simplified_content,
                    timestamp=part.timestamp
                ))
        else:
            new_parts.append(part)

    return replace(msg, parts=new_parts)


def _simplify_tool_response(
    msg: ModelResponse,
    msg_idx: int,
    last_positions: dict
) -> ModelResponse | None:
    """简化 ModelResponse 中的 ToolCallPart 和 ThinkingPart（截断非最新的）"""
    new_parts = []

    for part_idx, part in enumerate(msg.parts):
        if isinstance(part, ThinkingPart):
            is_last = (msg_idx, part_idx) == last_positions["thinking"]
            if is_last:
                new_parts.append(part)
            # 非最后的 ThinkingPart 直接跳过

        elif isinstance(part, ToolCallPart):
            is_last = (msg_idx, part_idx) == last_positions["tool_call"]
            if is_last:
                new_parts.append(part)
            else:
                simplified_args = _simplify_tool_args(part.args)
                new_parts.append(ToolCallPart(
                    tool_name=part.tool_name,
                    tool_call_id=part.tool_call_id,
                    args=simplified_args
                ))

        elif isinstance(part, TextPart):
            if len(part.content) > 500:
                truncated = part.content[:400] + "\n...[truncated]..."
                new_parts.append(TextPart(content=truncated))
            else:
                new_parts.append(part)
        else:
            new_parts.append(part)

    return replace(msg, parts=new_parts) if new_parts else None


def simplify_message_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """
    简化消息历史，减少 token 消耗

    符合 pydantic-ai HistoryProcessor 接口：
    - 输入：list[ModelMessage]
    - 输出：list[ModelMessage]
    """
    summary_text = "... truncated ..."
    last_positions = _find_last_positions(messages)

    simplified = []
    for msg_idx, msg in enumerate(messages):
        if isinstance(msg, ModelRequest):
            simplified_msg = _simplify_tool_request(msg, msg_idx, last_positions, summary_text)
            simplified.append(simplified_msg)

        elif isinstance(msg, ModelResponse):
            simplified_msg = _simplify_tool_response(msg, msg_idx, last_positions)
            if simplified_msg:
                simplified.append(simplified_msg)
        else:
            simplified.append(msg)

    return simplified


def _simplify_tool_args(args: dict | str) -> dict | str:
    """简化工具调用参数"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            if len(args) > 200:
                return args[:150] + "...[truncated]..."
            return args

    if isinstance(args, dict):
        simplified = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 200:
                simplified[key] = value[:100] + f"...[{len(value)} chars truncated]..."
            else:
                simplified[key] = value
        return simplified

    return args


def _truncate_content(content: Any, summary_text: str) -> str:
    """截断内容：保留前3行 + 说明 + 后3行"""
    if content is None:
        return summary_text
    if isinstance(content, dict):
        text = json.dumps(content, ensure_ascii=False, indent=2)
    else:
        text = str(content)

    all_lines = text.split('\n')
    non_empty_lines = [line for line in all_lines if line.strip()]

    if len(non_empty_lines) <= 8:
        return text

    head_lines = non_empty_lines[:3]
    tail_lines = non_empty_lines[-3:]

    if len(non_empty_lines) <= 6:
        return '\n'.join(non_empty_lines)

    return f"{chr(10).join(head_lines)}\n\n{summary_text}\n\n{chr(10).join(tail_lines)}"
