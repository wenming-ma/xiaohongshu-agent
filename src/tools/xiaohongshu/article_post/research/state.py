"""State helpers for article research iterations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from ..schemas import (
    ArticleResearchResult,
    ArticleResearchReviewResult,
    ArticleStrategy,
    ResearchDimensionReviewResult,
    SourceDigest,
)
from .tools import CollectedSource, SearchPlan, SearchResult


class ResearchBrief(BaseModel):
    objective: str = ""
    audience_focus: str = ""
    article_focuses: list[str] = Field(default_factory=list, max_length=4)
    video_focuses: list[str] = Field(default_factory=list, max_length=3)
    must_cover: list[str] = Field(default_factory=list, max_length=5)
    avoid_patterns: list[str] = Field(default_factory=list, max_length=4)
    iteration_guidance: str = ""


class ResearchTask(BaseModel):
    task_id: str = ""
    goal: str = ""
    source_focus: str = "balanced"
    article_queries: list[str] = Field(default_factory=list, max_length=3)
    video_queries: list[str] = Field(default_factory=list, max_length=2)
    done_when: str = ""
    avoid_patterns: list[str] = Field(default_factory=list, max_length=4)


class SupervisorPlan(BaseModel):
    summary: str = ""
    tasks: list[ResearchTask] = Field(default_factory=list, max_length=4)


class ResearchTaskResult(BaseModel):
    task_id: str
    goal: str = ""
    candidate_results: list[SearchResult] = Field(default_factory=list)
    collected_source_refs: list[str] = Field(default_factory=list)
    new_digests: list[SourceDigest] = Field(default_factory=list)
    raw_findings: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)


class CompressedResearchNote(BaseModel):
    task_id: str
    summary: str = ""
    key_findings: list[str] = Field(default_factory=list, max_length=5)
    unresolved_gaps: list[str] = Field(default_factory=list, max_length=4)
    recommended_next_queries: list[str] = Field(default_factory=list, max_length=4)
    source_refs: list[str] = Field(default_factory=list)


@dataclass
class ResearchState:
    topic: str
    target_audience: str
    strategy: ArticleStrategy
    output_dir: Path | None
    working_dir: Path | None = None

    brief: ResearchBrief | None = None
    supervisor_iteration: int = 0
    pending_tasks: list[ResearchTask] = field(default_factory=list)
    completed_task_results: list[ResearchTaskResult] = field(default_factory=list)
    current_notes: list[CompressedResearchNote] = field(default_factory=list)
    aggregated_notes: list[CompressedResearchNote] = field(default_factory=list)

    current_result: ArticleResearchResult | None = None
    current_review_result: ArticleResearchReviewResult | None = None
    current_dimension_reviews: list[ResearchDimensionReviewResult] = field(default_factory=list)
    current_plan: SearchPlan | None = None
    current_candidates: list[tuple[str, SearchResult]] = field(default_factory=list)
    current_task_candidates: dict[str, list[tuple[str, SearchResult]]] = field(default_factory=dict)
    current_collected: list[CollectedSource] = field(default_factory=list)
    current_digests: list[SourceDigest] = field(default_factory=list)

    collected_sources: list[CollectedSource] = field(default_factory=list)
    digests_by_source: dict[str, SourceDigest] = field(default_factory=dict)
    iteration_results: list[ArticleResearchResult] = field(default_factory=list)
    saved_files: list[str] = field(default_factory=list)
    evidence_files: list[str] = field(default_factory=list)
    digests_path: str = ""
    source_index_path: str = ""
    seen_candidate_urls: set[str] = field(default_factory=set)
    seen_source_urls: set[str] = field(default_factory=set)
    continuation_context: str = ""


def build_progress_snapshot(
    state: ResearchState,
    saved_file: str,
    validation_feedback: str,
    *,
    max_sources: int = 8,
) -> str:
    previews = []
    seen_refs: set[str] = set()
    for source in state.collected_sources:
        if source.ref in seen_refs:
            continue
        seen_refs.add(source.ref)
        label = source.title or source.url
        previews.append(f"- [{source.ref}] {source.domain} | {label}")
        if len(previews) >= max_sources:
            break

    task_lines = []
    for task in state.pending_tasks[:4]:
        task_lines.append(f"- {task.task_id or 'task'} | {task.goal}")
    task_text = "\n".join(task_lines) if task_lines else "- (none)"

    gap_lines = []
    for note in state.aggregated_notes[-4:]:
        for gap in note.unresolved_gaps[:2]:
            gap_lines.append(f"- [{note.task_id}] {gap}")
            if len(gap_lines) >= max_sources:
                break
        if len(gap_lines) >= max_sources:
            break
    gap_text = "\n".join(gap_lines) if gap_lines else "- (none)"

    preview_text = "\n".join(previews) if previews else "- (none)"
    saved_files = state.saved_files[:]
    if saved_file and saved_file not in saved_files:
        saved_files.append(saved_file)
    saved_files_text = "\n".join(f"- {item}" for item in saved_files[-max_sources:]) if saved_files else "- (none)"
    digest_refs = list(state.digests_by_source.keys())[:max_sources]
    digest_text = "\n".join(f"- {item}" for item in digest_refs) if digest_refs else "- (none)"
    review_lines = []
    if state.current_review_result is not None:
        review_lines.append(
            f"- 聚合评分: {state.current_review_result.score:.1f}/100"
        )
        if state.current_review_result.summary:
            review_lines.append(f"- 总结: {state.current_review_result.summary}")
        dimension_reviews = state.current_dimension_reviews or state.current_review_result.dimension_results
        for dimension_result in dimension_reviews:
            if dimension_result.summary:
                review_lines.append(f"- [{dimension_result.dimension.value}] {dimension_result.summary}")
                if len(review_lines) >= max_sources:
                    break
            for issue in dimension_result.issues[:1]:
                review_lines.append(f"- [{dimension_result.dimension.value}] {issue.description}")
                if len(review_lines) >= max_sources:
                    break
            if len(review_lines) >= max_sources:
                break
    review_text = "\n".join(review_lines) if review_lines else "- (none)"

    return (
        "上一轮研究未通过，请基于已有进展换一个搜索角度继续。\n\n"
        f"验证反馈:\n{validation_feedback}\n\n"
        f"审核摘要:\n{review_text}\n\n"
        f"已保存文件:\n{saved_files_text}\n\n"
        f"累计有效来源: {len(state.collected_sources)}\n"
        f"累计 digest 数: {len(state.digests_by_source)}\n"
        f"digest 来源:\n{digest_text}\n\n"
        f"最近任务:\n{task_text}\n\n"
        f"待补证据缺口:\n{gap_text}\n\n"
        f"已收集来源预览:\n{preview_text}\n\n"
        "请避免重复之前的 query 和页面，优先补足缺失域名、缺失视频来源或缺失 claim 支撑。"
    )
