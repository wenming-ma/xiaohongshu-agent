"""State helpers for article research iterations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import ArticleResearchResult, ArticleStrategy, SourceDigest
from .tools import CollectedSource, SearchPlan, SearchResult


@dataclass
class ResearchState:
    topic: str
    target_audience: str
    strategy: ArticleStrategy
    output_dir: Path | None
    working_dir: Path | None = None

    current_result: ArticleResearchResult | None = None
    current_plan: SearchPlan | None = None
    current_candidates: list[tuple[str, SearchResult]] = field(default_factory=list)
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

    preview_text = "\n".join(previews) if previews else "- (none)"
    saved_files = state.saved_files[:]
    if saved_file and saved_file not in saved_files:
        saved_files.append(saved_file)
    saved_files_text = "\n".join(f"- {item}" for item in saved_files[-max_sources:]) if saved_files else "- (none)"
    digest_refs = list(state.digests_by_source.keys())[:max_sources]
    digest_text = "\n".join(f"- {item}" for item in digest_refs) if digest_refs else "- (none)"

    return (
        "上一轮研究未通过，请基于已有进展换一个搜索角度继续。\n\n"
        f"验证反馈:\n{validation_feedback}\n\n"
        f"已保存文件:\n{saved_files_text}\n\n"
        f"累计有效来源: {len(state.collected_sources)}\n"
        f"累计 digest 数: {len(state.digests_by_source)}\n"
        f"digest 来源:\n{digest_text}\n\n"
        f"已收集来源预览:\n{preview_text}\n\n"
        "请避免重复之前的 query 和页面，优先补足缺失域名、缺失视频来源或缺失 claim 支撑。"
    )
