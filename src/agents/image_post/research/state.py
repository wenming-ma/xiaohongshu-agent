"""研究状态管理"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import ResearchResult


@dataclass
class ResearchState:
    """研究运行时状态"""
    topic: str
    target_audience: str
    output_dir: Path | None

    iteration_results: list[ResearchResult] = field(default_factory=list)
    saved_files: list[str] = field(default_factory=list)
    tracked_stats: dict = field(default_factory=dict)
    current_result: ResearchResult | None = None
    continuation_prompt: str | None = None


def build_progress_snapshot(state: ResearchState, saved_file: str, max_items: int = 10) -> str:
    """构建进度快照"""
    if not state.iteration_results:
        return ""

    seen_items: set[str] = set()
    seen_keywords: set[str] = set()
    merged_items: list = []

    for res in state.iteration_results:
        for item in res.items:
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
