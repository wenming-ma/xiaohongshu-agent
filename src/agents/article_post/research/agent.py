"""Cross-site deep research agent for long-form articles."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ....config.settings import PathConfig, RetryConfig
from ....core.base_agent import BaseAgent, ValidationResult
from ....utils.logger import get_logger
from ....utils.providers import get_text_model
from ..schemas import ArticleResearchResult, ArticleSource, ArticleSourceType, ArticleStrategy, SourceDigest, VideoTranscript
from .prompts import ITERATION_PLANNER_SYSTEM_PROMPT, SOURCE_DIGEST_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT, TASK_NOTE_SYSTEM_PROMPT, iteration_planner_prompt, source_digest_prompt, synthesis_user_prompt, task_note_prompt
from .state import CompressedResearchNote, IterationExecution, IterationPlan, QueryCandidate, ResearchState, ResearchTask, ResearchTaskResult, TaskAssessment, build_progress_snapshot
from .tools import ARTICLE_MEDIA_DOMAINS, VIDEO_MEDIA_DOMAINS, ArticlePageReader, CollectedSource, CollectedSourceCandidate, DomainSearchClient, GenericVideoTranscriber, LocalEvidenceStore, ReadPageResult, SearchResult, build_site_queries, is_article_media_domain, is_video_candidate, score_candidate, select_best_video_url
from ..utils.research import (
    SourceChunker,
    clean_list,
    json_dumps,
    save_iteration_result,
    save_latest_snapshot,
    unique_keep_order,
)
from ...shared.utils.tail_soft_limit import build_tail_soft_limit_history_processor
from .validator import ResearchReviewValidator, ResearchRulesValidator

logger = get_logger(__name__)

class IterationPlanner:
    def __init__(self, *, max_tasks_per_iteration: int = 4):
        self.max_tasks_per_iteration = max_tasks_per_iteration
        self._agent = Agent(
            model=get_text_model(),
            output_type=IterationPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(ITERATION_PLANNER_SYSTEM_PROMPT,),
        )

    async def plan_iteration(
        self,
        state: ResearchState,
        *,
        iteration: int,
    ) -> IterationPlan:
        notes_payload = [note.model_dump(mode="json") for note in state.aggregated_notes[-6:]]
        try:
            result = await self._agent.run(
                iteration_planner_prompt(
                    topic=state.topic,
                    target_audience=state.target_audience,
                    requested_strategy=state.strategy.value,
                    notes_json=json_dumps(notes_payload),
                    continuation_context=state.continuation_context,
                )
            )
            plan = result.output
        except Exception as exc:
            logger.warning("研究计划生成失败，使用回退任务: %s", exc)
            plan = IterationPlan()
        return self._normalize_plan(state, plan, iteration=iteration)

    def _normalize_plan(
        self,
        state: ResearchState,
        plan: IterationPlan,
        *,
        iteration: int,
    ) -> IterationPlan:
        objective = plan.objective.strip() or f"围绕 {state.topic} 形成可发布的小红书长文研究底稿"
        audience_focus = plan.audience_focus.strip() or state.target_audience
        avoid_patterns = clean_list(
            plan.avoid_patterns,
            fallback=["重复 query", "重复来源", "重复 claim"],
            limit=6,
        )
        fallback_tasks = self._fallback_tasks(state)
        candidates = plan.tasks or fallback_tasks
        tasks: list[ResearchTask] = []
        for idx, task in enumerate(candidates[: self.max_tasks_per_iteration], start=1):
            fallback = fallback_tasks[min(idx - 1, len(fallback_tasks) - 1)]
            tasks.append(
                ResearchTask(
                    task_id=task.task_id.strip() or f"iter_{iteration}_task_{idx}",
                    goal=task.goal.strip() or fallback.goal,
                    source_focus=task.source_focus.strip() or fallback.source_focus,
                    article_queries=clean_list(
                        task.article_queries,
                        fallback=fallback.article_queries,
                        limit=3,
                    ),
                    video_queries=clean_list(
                        task.video_queries,
                        fallback=fallback.video_queries,
                        limit=2,
                    ),
                    done_when=task.done_when.strip() or fallback.done_when,
                    avoid_patterns=clean_list(
                        task.avoid_patterns,
                        fallback=avoid_patterns,
                        limit=4,
                    ),
                )
            )
        if not tasks:
            tasks = [
                fallback.model_copy(update={"task_id": f"iter_{iteration}_task_{idx}"})
                for idx, fallback in enumerate(fallback_tasks, start=1)
            ]
        notes = plan.notes.strip() or "优先补齐来源广度、关键 claims 证据和可用视频补证"
        return IterationPlan(
            objective=objective,
            audience_focus=audience_focus,
            tasks=tasks,
            avoid_patterns=avoid_patterns,
            notes=notes,
        )

    def _fallback_tasks(self, state: ResearchState) -> list[ResearchTask]:
        topic = state.topic.strip()
        return [
            ResearchTask(
                goal=f"{topic} 的主论点、趋势和产业结构",
                source_focus="article",
                article_queries=[topic, f"{topic} analysis"],
                video_queries=[],
                done_when="拿到 3 个以上高质量文章来源并形成可复用结论",
                avoid_patterns=["重复 query", "重复来源", "重复 claim"],
            ),
            ResearchTask(
                goal=f"{topic} 的案例补证、媒体包装或视频证据",
                source_focus="video" if state.strategy.value == "repurpose_video" else "mixed",
                article_queries=[f"{topic} case study", f"{topic} media analysis"],
                video_queries=[f"{topic} interview", f"{topic} video analysis"],
                done_when="补齐 1 个以上可转录视频或关键案例来源",
                avoid_patterns=["重复 query", "重复来源", "重复 claim"],
            ),
        ]

class SourceDigestDraft(BaseModel):
    summary: str = ""
    key_points: list[str] = Field(default_factory=list, max_length=5)
    evidence_queries: list[str] = Field(default_factory=list, max_length=4)
    risk_notes: str = ""


class SourceDigestorAgent:
    def __init__(self, model: Any | None = None):
        self._agent = Agent(
            model=model or get_text_model(),
            output_type=SourceDigestDraft,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(SOURCE_DIGEST_SYSTEM_PROMPT,),
        )

    async def build_digest(
        self,
        *,
        topic: str,
        target_audience: str,
        source: CollectedSource,
        chunks: list[Any],
    ) -> SourceDigest:
        payload = {
            "source_ref": source.ref,
            "source_type": source.source_type,
            "url": source.url,
            "domain": source.domain,
            "title": source.title,
            "author": source.author,
            "published_at": source.published_at,
            "quality_score": source.quality_score,
            "engagement_hint": source.engagement_hint,
            "paywall_status": source.paywall_status,
            "transcript_available": bool(source.transcript),
            "headings": source.headings[:20],
        }
        chunk_payload = [
            {
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "heading": chunk.heading,
                "order": chunk.order,
                "text": chunk.text,
            }
            for chunk in chunks[:24]
        ]
        result = await self._agent.run(
            source_digest_prompt(
                topic=topic,
                target_audience=target_audience,
                source_json=json_dumps(payload),
                chunks_json=json_dumps(chunk_payload),
            )
        )
        draft = result.output
        return SourceDigest(
            source_ref=source.ref,
            source_type=ArticleSourceType(source.source_type),
            url=source.url,
            domain=source.domain,
            title=source.title,
            author=source.author,
            published_at=source.published_at,
            quality_score=source.quality_score,
            engagement_hint=source.engagement_hint,
            paywall_status=source.paywall_status,
            transcript_available=bool(source.transcript),
            headings=source.headings[:20],
            chunk_count=len(chunks),
            summary=draft.summary,
            key_points=[item.strip() for item in draft.key_points if item.strip()][:5],
            evidence_queries=[item.strip() for item in draft.evidence_queries if item.strip()][:4],
            risk_notes=draft.risk_notes.strip(),
        )


class CollectorCurator:
    def __init__(
        self,
        *,
        model: Any | None = None,
        search_client: DomainSearchClient | None = None,
        page_reader: ArticlePageReader | None = None,
        video_transcriber: GenericVideoTranscriber | None = None,
        chunker: SourceChunker | None = None,
        note_compressor: Agent | None = None,
        digestor: SourceDigestorAgent | None = None,
        max_source_pages: int = 10,
        max_video_transcripts: int = 2,
        search_concurrency: int = 3,
        page_visit_concurrency: int = 3,
        min_curation_quality_score: float = 72.0,
        max_curated_sources_per_task: int = 3,
        max_curated_video_sources_per_task: int = 2,
        min_curated_sources_for_note_compression: int = 2,
    ):
        self.model = model or get_text_model()
        self.search_client = search_client or DomainSearchClient()
        self.page_reader = page_reader or ArticlePageReader()
        self.video_transcriber = video_transcriber or GenericVideoTranscriber()
        self.chunker = chunker or SourceChunker()
        self.note_compressor = note_compressor or Agent(
            model=self.model,
            output_type=CompressedResearchNote,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(TASK_NOTE_SYSTEM_PROMPT,),
        )
        self.digestor = digestor or SourceDigestorAgent(self.model)
        self.MAX_SOURCE_PAGES = max_source_pages
        self.MAX_VIDEO_TRANSCRIPTS = max_video_transcripts
        self.SEARCH_CONCURRENCY = search_concurrency
        self.PAGE_VISIT_CONCURRENCY = page_visit_concurrency
        self.MIN_CURATION_QUALITY_SCORE = min_curation_quality_score
        self.MAX_CURATED_SOURCES_PER_TASK = max_curated_sources_per_task
        self.MAX_CURATED_VIDEO_SOURCES_PER_TASK = max_curated_video_sources_per_task
        self.MIN_CURATED_SOURCES_FOR_NOTE_COMPRESSION = min_curated_sources_for_note_compression

    async def execute_iteration(self, state: ResearchState, tasks: list[ResearchTask]) -> IterationExecution:
        candidate_pool, task_candidates = await self.search_candidates(tasks, state)
        execution = IterationExecution(candidate_pool=candidate_pool, task_candidates=task_candidates)
        for task in tasks:
            assessment = await self.run_task(
                state=state,
                task=task,
                candidates=execution.task_candidates.get(task.task_id, []),
                execution=execution,
            )
            execution.task_assessments.append(assessment)
            if assessment.note is not None:
                execution.notes.append(assessment.note)
        return execution

    async def search_candidates(
        self,
        tasks: list[ResearchTask],
        state: ResearchState,
    ) -> tuple[list[QueryCandidate], dict[str, list[QueryCandidate]]]:
        query_to_tasks: dict[str, list[str]] = {}
        for task in tasks:
            for query in self._compile_task_queries(task):
                query_to_tasks.setdefault(query, [])
                if task.task_id not in query_to_tasks[query]:
                    query_to_tasks[query].append(task.task_id)
        if not query_to_tasks:
            return [], {}

        sem = asyncio.Semaphore(self.SEARCH_CONCURRENCY)

        async def _run(query: str) -> tuple[str, list[SearchResult]]:
            async with sem:
                try:
                    return query, await self.search_client.search(query, max_results=4)
                except Exception as exc:
                    logger.warning("搜索 query 失败，已跳过: %s (%s)", query, exc)
                    return query, []

        pairs = await asyncio.gather(*[_run(query) for query in query_to_tasks])
        result_by_url: dict[str, QueryCandidate] = {}
        task_urls: dict[str, list[str]] = {task.task_id: [] for task in tasks}

        for query, results in pairs:
            for result in results:
                if not result.url or result.url in state.seen_candidate_urls:
                    continue
                result_by_url.setdefault(result.url, QueryCandidate(query=query, result=result))
                for task_id in query_to_tasks.get(query, []):
                    task_urls.setdefault(task_id, []).append(result.url)

        for url in result_by_url:
            state.seen_candidate_urls.add(url)

        task_candidates: dict[str, list[QueryCandidate]] = {}
        for task in tasks:
            seen_urls: set[str] = set()
            task_candidates[task.task_id] = []
            for url in task_urls.get(task.task_id, []):
                if url in seen_urls or url not in result_by_url:
                    continue
                seen_urls.add(url)
                task_candidates[task.task_id].append(result_by_url[url])

        return list(result_by_url.values()), task_candidates

    async def run_task(
        self,
        *,
        state: ResearchState,
        task: ResearchTask,
        candidates: list[QueryCandidate],
        execution: IterationExecution,
    ) -> TaskAssessment:
        prioritized_candidates = self._prioritize_task_candidates(task, candidates)
        raw_candidates, collected, curation_notes = await self.collect_task_sources(
            task,
            prioritized_candidates,
            state,
            execution=execution,
        )
        if collected:
            execution.collected.extend(collected)
            state.collected_sources.extend(collected)

        task_digests = await self._build_task_digests(state, collected)
        if task_digests:
            execution.digests.extend(task_digests)

        assessment = TaskAssessment(
            task_id=task.task_id,
            goal=task.goal,
            candidate_results=[candidate.result for candidate in prioritized_candidates],
            raw_source_count=len(raw_candidates),
            curated_source_count=len(collected),
            collected_source_refs=[source.ref for source in collected],
            new_digests=task_digests,
            raw_findings=self._collect_raw_findings(task_digests),
            gaps=self._collect_task_gaps(task, raw_candidates, collected, task_digests, curation_notes),
            suggested_followups=[],
            curation_notes=curation_notes,
        )
        assessment.suggested_followups = self._collect_task_followups(task, task_digests, assessment.gaps)
        assessment.note = await self.compress_task_result(task, assessment)
        return assessment

    async def visit_and_collect_sources(
        self,
        task: ResearchTask,
        candidates: list[QueryCandidate],
        state: ResearchState,
        *,
        execution: IterationExecution | None = None,
    ) -> list[CollectedSource]:
        _, collected, _ = await self.collect_task_sources(task, candidates, state, execution=execution)
        return collected

    async def collect_task_sources(
        self,
        task: ResearchTask,
        candidates: list[QueryCandidate],
        state: ResearchState,
        *,
        execution: IterationExecution | None = None,
    ) -> tuple[list[CollectedSourceCandidate], list[CollectedSource], list[str]]:
        raw_candidates = await self._read_task_source_candidates(task, candidates, state, execution=execution)
        curated_candidates, curation_notes = self._curate_task_sources(task, raw_candidates, state, execution=execution)
        collected = self._finalize_curated_sources(state, curated_candidates)
        return raw_candidates, collected, curation_notes
    async def _read_task_source_candidates(
        self,
        task: ResearchTask,
        candidates: list[QueryCandidate],
        state: ResearchState,
        *,
        execution: IterationExecution | None = None,
    ) -> list[CollectedSourceCandidate]:
        collected: list[CollectedSourceCandidate] = []
        current_execution = execution or state.current_execution or IterationExecution()
        videos_used = sum(1 for source in state.collected_sources if source.transcript)
        wants_video = self._task_wants_video(task, state.strategy)
        remaining_slots = self.MAX_SOURCE_PAGES - len(current_execution.collected)
        if remaining_slots <= 0 or not candidates:
            return collected

        sem = asyncio.Semaphore(self.PAGE_VISIT_CONCURRENCY)
        raw_limit = min(len(candidates), max(remaining_slots, self._task_curated_cap(task) * 2))

        async def _read_candidate(candidate: QueryCandidate) -> tuple[QueryCandidate, ReadPageResult]:
            async with sem:
                return candidate, await self.page_reader.read_page(candidate.result.url)

        read_results = await asyncio.gather(*(_read_candidate(candidate) for candidate in candidates[:raw_limit]))
        for candidate, read_result in read_results:
            result = candidate.result
            if not read_result.ok:
                logger.warning("跳过(提取失败): %s notes=%s", result.url, read_result.notes[:120])
                continue
            final_url = read_result.final_url or result.url
            if final_url in state.seen_source_urls:
                logger.info("跳过(已访问): %s", final_url)
                continue
            state.seen_source_urls.add(final_url)
            if read_result.paywall_status == "login_required" and len(read_result.text) < 1200:
                logger.info("跳过(付费墙+短文): %s text=%d", result.url, len(read_result.text))
                continue
            if len(read_result.text) < 1200 and not is_video_candidate(result.url, read_result):
                logger.info("跳过(文本太短): %s text=%d", result.url, len(read_result.text))
                continue

            source_type = ArticleSourceType.ARTICLE
            transcript_text = ""
            duration_seconds = 0.0
            if (
                is_video_candidate(result.url, read_result)
                and videos_used < self.MAX_VIDEO_TRANSCRIPTS
                and (wants_video or not any(source.transcript for source in state.collected_sources))
            ):
                video_url = select_best_video_url(read_result, result.url)
                if video_url:
                    transcript_result = await self.video_transcriber.transcribe(video_url)
                    if transcript_result.success:
                        source_type = (
                            ArticleSourceType.VIDEO
                            if not is_article_media_domain(urlsplit(result.url).netloc.lower())
                            else ArticleSourceType.EMBEDDED_VIDEO
                        )
                        transcript_text = transcript_result.transcript
                        duration_seconds = transcript_result.duration_seconds
                        videos_used += 1
                else:
                    logger.info("跳过视频转录(缺少可用视频地址): %s", result.url)

            quality_score = score_candidate(
                result,
                read_result,
                wants_video=source_type != ArticleSourceType.ARTICLE,
            )
            collected.append(
                CollectedSourceCandidate(
                    url=final_url,
                    domain=urlsplit(final_url).netloc.lower(),
                    title=read_result.title or result.title,
                    author=read_result.author,
                    published_at=read_result.published_at,
                    snippet=result.snippet,
                    text=read_result.text,
                    headings=read_result.headings,
                    paragraphs=read_result.paragraphs,
                    source_type=source_type.value,
                    engagement_hint=read_result.engagement_hint or f"search_rank={result.rank} query={candidate.query[:80]}",
                    paywall_status=read_result.paywall_status,
                    quality_score=quality_score,
                    transcript=transcript_text,
                    duration_seconds=duration_seconds,
                    search_rank=result.rank,
                    query=candidate.query,
                )
            )
        return collected

    def _curate_task_sources(
        self,
        task: ResearchTask,
        raw_candidates: list[CollectedSourceCandidate],
        state: ResearchState | IterationExecution,
        *,
        execution: IterationExecution | None = None,
    ) -> tuple[list[CollectedSourceCandidate], list[str]]:
        if isinstance(state, IterationExecution):
            current_execution = execution or state
        else:
            current_execution = execution or state.current_execution or IterationExecution()
        remaining_slots = self.MAX_SOURCE_PAGES - len(current_execution.collected)
        curated_cap = min(self._task_curated_cap(task), max(0, remaining_slots))
        if curated_cap <= 0 or not raw_candidates:
            return [], []

        ranked_candidates = sorted(
            enumerate(raw_candidates),
            key=lambda item: (self._score_curated_source(task, item[1]), -item[0]),
            reverse=True,
        )
        eligible: list[CollectedSourceCandidate] = []
        rejected: dict[str, str] = {}
        for _, candidate in ranked_candidates:
            reason = self._reject_candidate_reason(task, candidate)
            if reason:
                rejected[candidate.url] = self._format_curation_note(reason, candidate)
                continue
            eligible.append(candidate)

        curated: list[CollectedSourceCandidate] = []
        kept_urls: set[str] = set()
        kept_domains: set[str] = set()
        for candidate in eligible:
            if len(curated) >= curated_cap:
                break
            if candidate.domain in kept_domains:
                continue
            curated.append(candidate)
            kept_urls.add(candidate.url)
            kept_domains.add(candidate.domain)

        for candidate in eligible:
            if len(curated) >= curated_cap:
                break
            if candidate.url in kept_urls:
                continue
            curated.append(candidate)
            kept_urls.add(candidate.url)

        curation_notes = list(rejected.values())
        for candidate in eligible:
            if candidate.url in kept_urls:
                continue
            if candidate.domain in kept_domains:
                curation_notes.append(self._format_curation_note("duplicate_domain", candidate))
            else:
                curation_notes.append(self._format_curation_note("weak_task_fit", candidate))
        return curated, unique_keep_order(curation_notes)[:8]

    def _finalize_curated_sources(
        self,
        state: ResearchState,
        curated_candidates: list[CollectedSourceCandidate],
    ) -> list[CollectedSource]:
        finalized: list[CollectedSource] = []
        start_index = len(state.collected_sources)
        for offset, candidate in enumerate(curated_candidates, start=1):
            finalized.append(
                CollectedSource(
                    ref=f"source_{start_index + offset}",
                    url=candidate.url,
                    domain=candidate.domain,
                    title=candidate.title,
                    author=candidate.author,
                    published_at=candidate.published_at,
                    snippet=candidate.snippet,
                    text=candidate.text,
                    headings=candidate.headings,
                    paragraphs=candidate.paragraphs,
                    source_type=candidate.source_type,
                    engagement_hint=candidate.engagement_hint,
                    paywall_status=candidate.paywall_status,
                    quality_score=candidate.quality_score,
                    transcript=candidate.transcript,
                    duration_seconds=candidate.duration_seconds,
                )
            )
        return finalized

    @classmethod
    def _prioritize_task_candidates(
        cls,
        task: ResearchTask,
        candidates: list[QueryCandidate],
    ) -> list[QueryCandidate]:
        return [
            candidate
            for _, candidate in sorted(
                enumerate(candidates),
                key=lambda item: (cls._score_task_candidate(task, item[1].query, item[1].result), -(item[1].result.rank or 0)),
                reverse=True,
            )
        ]

    @classmethod
    def _score_task_candidate(cls, task: ResearchTask, query: str, result: SearchResult) -> float:
        terms = cls._extract_relevance_terms(task.goal, *task.article_queries, *task.video_queries)
        title = (result.title or "").lower()
        snippet = (result.snippet or "").lower()
        url = (result.url or "").lower()
        score = float(max(0, 8 - (result.rank or 0)))
        title_hits = {term for term in terms if term in title}
        snippet_hits = {term for term in terms if term in snippet}
        url_hits = {term for term in terms if term in url}
        score += len(title_hits) * 5.0
        score += len(snippet_hits - title_hits) * 2.0
        score += len(url_hits - title_hits - snippet_hits) * 1.0
        if "site:" not in query.lower():
            score += 2.0
        return score

    @staticmethod
    def _extract_relevance_terms(*texts: str) -> list[str]:
        stopwords = {
            "about", "after", "article", "articles", "balanced", "could", "image", "into",
            "media", "paris", "parisian", "style", "their", "these", "they", "this",
            "video", "videos", "what", "when", "which", "with", "woman", "women",
        }
        seen: set[str] = set()
        terms: list[str] = []
        for text in texts:
            normalized = re.sub(r"site:\S+", " ", str(text).lower())
            for token in re.findall(r"[a-z0-9][a-z0-9_-]+", normalized):
                cleaned = token.strip("_-")
                if len(cleaned) < 4 or cleaned in stopwords or cleaned in seen:
                    continue
                seen.add(cleaned)
                terms.append(cleaned)
        return terms
    async def _build_task_digests(
        self,
        state: ResearchState,
        sources: list[CollectedSource],
    ) -> list[SourceDigest]:
        digests: list[SourceDigest] = []
        for source in sources:
            if source.ref in state.digests_by_source:
                digests.append(state.digests_by_source[source.ref])
                continue
            chunks = self.chunker.chunk(source)
            state.digests_by_source[source.ref] = await self.digestor.build_digest(
                topic=state.topic,
                target_audience=state.target_audience,
                source=source,
                chunks=chunks,
            )
            digests.append(state.digests_by_source[source.ref])
        return digests

    async def compress_task_result(
        self,
        task: ResearchTask,
        task_result: ResearchTaskResult,
    ) -> CompressedResearchNote:
        if not self._should_compress_task_result(task_result):
            return self._build_fallback_task_note(task, task_result)
        try:
            result = await self.note_compressor.run(
                task_note_prompt(
                    task_json=json_dumps(task.model_dump(mode="json")),
                    result_json=json_dumps(task_result.model_dump(mode="json")),
                    digests_json=json_dumps([digest.model_dump(mode="json") for digest in task_result.new_digests]),
                )
            )
            note = result.output
        except Exception as exc:
            logger.warning("研究任务 notes 压缩失败，使用回退结果: %s", exc)
            return self._build_fallback_task_note(task, task_result)
        return self._normalize_task_note(task, task_result, note)

    def _normalize_task_note(
        self,
        task: ResearchTask,
        task_result: ResearchTaskResult,
        note: CompressedResearchNote,
    ) -> CompressedResearchNote:
        summary = note.summary.strip() or (task_result.raw_findings[0] if task_result.raw_findings else f"{task.goal} 新增信息有限")
        key_findings = clean_list(note.key_findings, fallback=task_result.raw_findings, limit=5)
        unresolved_gaps = clean_list(note.unresolved_gaps, fallback=task_result.gaps, limit=4)
        recommended_next_queries = clean_list(note.recommended_next_queries, fallback=task_result.suggested_followups, limit=4)
        source_refs = clean_list(note.source_refs, fallback=task_result.collected_source_refs, limit=8)
        return CompressedResearchNote(
            task_id=task.task_id,
            summary=summary,
            key_findings=key_findings,
            unresolved_gaps=unresolved_gaps,
            recommended_next_queries=recommended_next_queries,
            source_refs=source_refs,
        )

    def _collect_raw_findings(self, digests: list[SourceDigest]) -> list[str]:
        findings: list[str] = []
        for digest in digests:
            if digest.summary.strip():
                findings.append(digest.summary.strip())
            findings.extend(point.strip() for point in digest.key_points if point.strip())
        return unique_keep_order(findings)[:8]

    def _collect_task_gaps(
        self,
        task: ResearchTask,
        raw_candidates: list[CollectedSourceCandidate],
        collected: list[CollectedSource],
        digests: list[SourceDigest],
        curation_notes: list[str],
    ) -> list[str]:
        gaps: list[str] = []
        if not raw_candidates:
            gaps.append("未找到可用主来源")
        elif not collected:
            gaps.append("找到候选来源但未通过质量筛选")
        if self._is_video_focused_task(task) and not any(source.transcript for source in collected):
            gaps.append("缺少可用视频转录")
        if any(note.startswith("video_without_transcript:") for note in curation_notes):
            gaps.append("视频候选缺少可用转录")
        if len({source.domain for source in collected}) < 2:
            gaps.append("来源域名仍偏少")
        if not any(digest.key_points for digest in digests):
            gaps.append("高价值结论仍不够明确")
        return unique_keep_order(gaps)[:4]

    def _task_curated_cap(self, task: ResearchTask) -> int:
        if self._is_video_focused_task(task):
            return self.MAX_CURATED_VIDEO_SOURCES_PER_TASK
        return self.MAX_CURATED_SOURCES_PER_TASK

    @staticmethod
    def _is_video_focused_task(task: ResearchTask) -> bool:
        return "video" in (task.source_focus or "").lower()

    @classmethod
    def _task_wants_video(cls, task: ResearchTask, strategy: ArticleStrategy) -> bool:
        return cls._is_video_focused_task(task) or strategy == ArticleStrategy.REPURPOSE_VIDEO

    @staticmethod
    def _candidate_is_video(candidate: CollectedSourceCandidate) -> bool:
        source_url = (candidate.url or "").lower()
        return candidate.source_type != ArticleSourceType.ARTICLE.value or any(
            pattern in source_url for pattern in ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com")
        )

    def _reject_candidate_reason(self, task: ResearchTask, candidate: CollectedSourceCandidate) -> str:
        if candidate.quality_score < self.MIN_CURATION_QUALITY_SCORE:
            return "low_quality"
        if self._is_video_focused_task(task) and self._candidate_is_video(candidate) and not candidate.transcript:
            return "video_without_transcript"
        if self._source_task_fit_score(task, candidate) <= 0.0:
            return "weak_task_fit"
        return ""

    def _score_curated_source(self, task: ResearchTask, candidate: CollectedSourceCandidate) -> float:
        score = candidate.quality_score
        score += self._source_task_fit_score(task, candidate)
        if candidate.author:
            score += 1.5
        if candidate.published_at:
            score += 1.5
        if candidate.transcript:
            score += 2.0
            if self._is_video_focused_task(task):
                score += 4.0
        if candidate.search_rank:
            score += max(0.0, 5.0 - float(candidate.search_rank))
        return score

    @classmethod
    def _source_task_fit_score(cls, task: ResearchTask, candidate: CollectedSourceCandidate) -> float:
        terms = cls._extract_relevance_terms(task.goal, *task.article_queries, *task.video_queries)
        if not terms:
            return 0.0
        title = (candidate.title or "").lower()
        snippet = (candidate.snippet or "").lower()
        url = (candidate.url or "").lower()
        headings = " ".join(candidate.headings[:10]).lower()
        title_hits = {term for term in terms if term in title}
        snippet_hits = {term for term in terms if term in snippet}
        url_hits = {term for term in terms if term in url}
        heading_hits = {term for term in terms if term in headings}
        score = len(title_hits) * 4.0
        score += len(snippet_hits - title_hits) * 2.0
        score += len(heading_hits - title_hits - snippet_hits) * 1.5
        score += len(url_hits - title_hits - snippet_hits - heading_hits) * 1.0
        return score

    @staticmethod
    def _format_curation_note(reason: str, candidate: CollectedSourceCandidate) -> str:
        return f"{reason}: {candidate.url or candidate.domain}"

    def _collect_task_followups(self, task: ResearchTask, digests: list[SourceDigest], gaps: list[str]) -> list[str]:
        followups: list[str] = []
        for digest in digests:
            followups.extend(item.strip() for item in digest.evidence_queries if item.strip())
        if not followups and gaps:
            followups.extend(task.article_queries[:2])
            followups.extend(task.video_queries[:1])
        return unique_keep_order(followups)[:4]

    def _should_compress_task_result(self, task_result: ResearchTaskResult) -> bool:
        if not task_result.collected_source_refs:
            return False
        if task_result.curated_source_count >= self.MIN_CURATED_SOURCES_FOR_NOTE_COMPRESSION:
            return True
        return len(task_result.new_digests) >= self.MIN_CURATED_SOURCES_FOR_NOTE_COMPRESSION

    def _build_fallback_task_note(self, task: ResearchTask, task_result: ResearchTaskResult) -> CompressedResearchNote:
        if not task_result.collected_source_refs:
            if task_result.raw_source_count > 0:
                summary = f"{task.goal or task.task_id} 找到 {task_result.raw_source_count} 个候选，但经筛选后未保留可用来源"
            else:
                summary = f"{task.goal or task.task_id} 暂未找到可用来源"
        elif task_result.raw_findings:
            summary = task_result.raw_findings[0]
        else:
            summary = f"{task.goal or task.task_id} 新增 {task_result.curated_source_count} 个可用来源"
        return self._normalize_task_note(
            task,
            task_result,
            CompressedResearchNote(
                task_id=task.task_id,
                summary=summary,
                key_findings=task_result.raw_findings[:5],
                unresolved_gaps=task_result.gaps[:4],
                recommended_next_queries=task_result.suggested_followups[:4],
                source_refs=task_result.collected_source_refs[:8],
            ),
        )

    def compile_task_queries(self, task: ResearchTask) -> list[str]:
        return self._compile_task_queries(task)

    @staticmethod
    def _compile_task_queries(task: ResearchTask) -> list[str]:
        article_seed = [item.strip() for item in task.article_queries if item.strip()]
        video_seed = [item.strip() for item in task.video_queries if item.strip()]
        goal_seed = task.goal.strip() if task.goal.strip() else "women lifestyle trend"
        if not article_seed:
            article_seed = [goal_seed]
        if not video_seed:
            video_seed = [f"{goal_seed} interview"]
        article_queries = build_site_queries(article_seed[:2], ARTICLE_MEDIA_DOMAINS, max_domains_per_query=2, max_total_queries=4)
        video_queries = build_site_queries(video_seed[:2], VIDEO_MEDIA_DOMAINS, max_domains_per_query=2, max_total_queries=4)
        article_open_queries = [q for q in article_seed[:2] if q]
        video_open_queries = [q for q in video_seed[:1] if q]
        if "video" in task.source_focus.lower():
            return unique_keep_order(video_queries + video_open_queries + article_queries + article_open_queries[:1])
        return unique_keep_order(article_queries + article_open_queries + video_queries + video_open_queries)

class SynthesizerValidator:
    def __init__(
        self,
        *,
        model=None,
        chunker: SourceChunker | None = None,
        digestor: SourceDigestorAgent | None = None,
        min_source_pages: int = 8,
        min_unique_domains: int = 6,
        max_iterations: int = 3,
        min_digests_for_full_synthesis: int = 2,
    ) -> None:
        self.model = model or get_text_model()
        self.chunker = chunker or SourceChunker()
        self.digestor = digestor or SourceDigestorAgent(model=self.model)
        self.rules_validator = ResearchRulesValidator()
        self.review_validator = ResearchReviewValidator()
        self.min_source_pages = min_source_pages
        self.min_unique_domains = min_unique_domains
        self.max_iterations = max_iterations
        self.min_digests_for_full_synthesis = min_digests_for_full_synthesis

    async def prepare_iteration(
        self,
        state: ResearchState,
        iteration: int,
    ) -> None:
        execution = state.current_execution or IterationExecution()
        state.current_execution = execution
        if not self.should_run_full_iteration_synthesis(state, iteration):
            execution.synthesized = False
            execution.skip_reason = self.build_iteration_skip_reason(state)
            return

        execution.synthesized = True
        execution.skip_reason = ""
        evidence_store = LocalEvidenceStore(state.working_dir or state.output_dir or Path("output"))
        state.current_result = await self.synthesize_result(state, evidence_store)

    async def synthesize_result(
        self,
        state: ResearchState,
        evidence_store: LocalEvidenceStore,
    ) -> ArticleResearchResult:
        evidence_files, digests_path, source_index_path = await self._build_local_evidence(
            state=state,
            evidence_store=evidence_store,
        )
        state.evidence_files = evidence_files
        state.digests_path = digests_path
        state.source_index_path = source_index_path

        payload = self._build_digest_payload(state)
        synthesizer = self._create_synthesizer(evidence_store)
        result = await synthesizer.run(
            synthesis_user_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                requested_strategy=state.strategy.value,
                current_date=datetime.now().date().isoformat(),
                brief_json=json_dumps(
                    state.current_iteration_plan.model_dump(mode="json")
                    if state.current_iteration_plan is not None
                    else {}
                ),
                notes_json=json_dumps(
                    [note.model_dump(mode="json") for note in state.aggregated_notes[-12:]]
                ),
                digest_payload_json=json_dumps(payload),
            )
        )
        research = result.output
        research.sources = self._build_sources(state.collected_sources)
        research.transcripts = self._build_transcripts(state.collected_sources)
        self._normalize_research_result(research, state.collected_sources)
        if not research.primary_source_ref and state.collected_sources:
            research.primary_source_ref = state.collected_sources[0].ref
        if state.strategy != ArticleStrategy.AUTO:
            research.suggested_strategy = state.strategy
        elif research.suggested_strategy == ArticleStrategy.AUTO:
            research.suggested_strategy = ArticleStrategy.SYNTHESIZE
        return research

    async def validate(
        self,
        state: ResearchState | None,
        output: Any,
    ) -> ValidationResult:
        rules_result = await self.rules_validator.validate(
            output,
            context={
                "min_source_pages": self.min_source_pages,
                "min_unique_domains": self.min_unique_domains,
            },
        )
        if not rules_result.passed:
            if state is not None:
                state.current_review_result = None
                state.current_dimension_reviews = []
            return ValidationResult.failure(rules_result.feedback)

        review_result = await self.review_validator.validate(
            output,
            context={
                "topic": state.topic if state is not None else "",
                "target_audience": state.target_audience if state is not None else "",
                "requested_strategy": state.strategy if state is not None else ArticleStrategy.AUTO,
                "output_dir": (
                    state.working_dir or state.output_dir
                    if state is not None
                    else None
                ),
            },
        )
        if state is not None:
            state.current_review_result = self.review_validator.last_review_result
            state.current_dimension_reviews = self.review_validator.last_dimension_results[:]

        if review_result.passed:
            return ValidationResult.success(f"研究通过，来源数 {output.sources_count}")
        return ValidationResult.failure(review_result.feedback)

    @staticmethod
    def _build_sources(collected: list[CollectedSource]) -> list[ArticleSource]:
        sources: list[ArticleSource] = []
        for item in collected:
            sources.append(
                ArticleSource(
                    source_ref=item.ref,
                    source_type=ArticleSourceType(item.source_type),
                    url=item.url,
                    domain=item.domain,
                    title=item.title,
                    author=item.author,
                    published_at=item.published_at,
                    excerpt=item.snippet,
                    quality_score=item.quality_score,
                    engagement_hint=item.engagement_hint,
                    paywall_status=item.paywall_status,
                    duration_seconds=(
                        item.duration_seconds
                        if item.source_type != ArticleSourceType.ARTICLE.value
                        else 0.0
                    ),
                    transcript_available=bool(item.transcript),
                )
            )
        return sources

    @staticmethod
    def _normalize_research_result(
        research: ArticleResearchResult,
        collected_sources: list[CollectedSource],
    ) -> None:
        available_refs = [source.ref for source in collected_sources if source.ref]
        available_ref_set = set(available_refs)
        normalized_claims = []
        dropped_claim_notes: list[str] = []

        for claim in research.claims:
            cleaned_refs: list[str] = []
            seen_refs: set[str] = set()
            for ref in claim.source_refs:
                cleaned_ref = str(ref).strip()
                if not cleaned_ref or cleaned_ref not in available_ref_set or cleaned_ref in seen_refs:
                    continue
                seen_refs.add(cleaned_ref)
                cleaned_refs.append(cleaned_ref)

            if not cleaned_refs:
                note = claim.claim.strip() or claim.detail.strip() or claim.section_hint.strip()
                if note:
                    dropped_claim_notes.append(note)
                continue

            claim.source_refs = cleaned_refs
            normalized_claims.append(claim)

        research.claims = normalized_claims

        if research.primary_source_ref and research.primary_source_ref not in available_ref_set:
            research.primary_source_ref = ""

        if dropped_claim_notes:
            prefix = "未纳入 claims 的证据缺口："
            gap_summary = "；".join(unique_keep_order(dropped_claim_notes)[:4])
            gap_note = f"{prefix}{gap_summary}"
            research.notes = (
                f"{research.notes.strip()}\n{gap_note}".strip()
                if research.notes.strip()
                else gap_note
            )

    @staticmethod
    def _build_transcripts(collected: list[CollectedSource]) -> list[VideoTranscript]:
        transcripts: list[VideoTranscript] = []
        for item in collected:
            if not item.transcript:
                continue
            transcripts.append(
                VideoTranscript(
                    success=True,
                    transcript=item.transcript,
                    language="unknown",
                    duration_seconds=item.duration_seconds,
                    source_ref=item.ref,
                )
            )
        return transcripts

    def _create_synthesizer(self, evidence_store: LocalEvidenceStore) -> Agent:
        return Agent(
            model=self.model,
            output_type=ArticleResearchResult,
            tools=evidence_store.get_tools(),
            history_processors=[
                build_tail_soft_limit_history_processor(
                    output_name="ArticleResearchResult",
                    threshold=50,
                )
            ],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(SYNTHESIS_SYSTEM_PROMPT,),
        )

    async def _build_local_evidence(
        self,
        *,
        state: ResearchState,
        evidence_store: LocalEvidenceStore,
    ) -> tuple[list[str], str, str]:
        chunks_by_source = {
            source.ref: self.chunker.chunk(source)
            for source in state.collected_sources
        }
        evidence_files = evidence_store.save_sources(state.collected_sources, chunks_by_source)

        for source in state.collected_sources:
            if source.ref in state.digests_by_source:
                continue
            state.digests_by_source[source.ref] = await self.digestor.build_digest(
                topic=state.topic,
                target_audience=state.target_audience,
                source=source,
                chunks=chunks_by_source.get(source.ref, []),
            )

        all_digests = [
            state.digests_by_source[source.ref]
            for source in state.collected_sources
            if source.ref in state.digests_by_source
        ]
        digests_path = evidence_store.save_digests(all_digests)
        return evidence_files, digests_path, str(evidence_store.index_path)

    def _build_digest_payload(self, state: ResearchState) -> dict[str, Any]:
        execution = state.current_execution or IterationExecution()
        return {
            "topic": state.topic,
            "target_audience": state.target_audience,
            "requested_strategy": state.strategy.value,
            "plan": (
                state.current_iteration_plan.model_dump(mode="json")
                if state.current_iteration_plan is not None
                else {}
            ),
            "notes": [note.model_dump(mode="json") for note in state.aggregated_notes[-12:]],
            "current_iteration_notes": [note.model_dump(mode="json") for note in execution.notes],
            "task_results": [
                {
                    "task_id": result.task_id,
                    "goal": result.goal,
                    "raw_source_count": result.raw_source_count,
                    "curated_source_count": result.curated_source_count,
                    "source_refs": result.collected_source_refs,
                    "gaps": result.gaps,
                    "suggested_followups": result.suggested_followups,
                    "curation_notes": result.curation_notes,
                }
                for result in execution.task_assessments
            ],
            "digests": [
                state.digests_by_source[source.ref].model_dump(mode="json")
                for source in state.collected_sources
                if source.ref in state.digests_by_source
            ],
            "source_refs": [source.ref for source in state.collected_sources],
            "available_tools": [
                "list_saved_sources",
                "read_source_digest",
                "read_source_excerpt",
                "read_primary_source",
            ],
        }

    def should_run_full_iteration_synthesis(
        self,
        state: ResearchState,
        iteration: int,
    ) -> bool:
        execution = state.current_execution or IterationExecution()
        if state.current_result is None:
            return True
        if iteration >= self.max_iterations - 1:
            return True
        if len(execution.digests) >= self.min_digests_for_full_synthesis:
            return True
        if len(execution.collected) >= self.min_digests_for_full_synthesis:
            return True
        if any(source.transcript for source in execution.collected):
            return True
        return False

    @staticmethod
    def build_iteration_skip_reason(state: ResearchState) -> str:
        execution = state.current_execution or IterationExecution()
        return (
            f"本轮仅新增 {len(execution.collected)} 个来源、"
            f"{len(execution.digests)} 个 digest，保留到下一轮合并"
        )

class ResearchAgent(BaseAgent):
    role = "跨站深度研究员"
    goal = "从海外高质量女性向媒体中提取高价值文章和视频信息"

    MIN_SOURCE_PAGES = 8
    MIN_UNIQUE_DOMAINS = 6
    MAX_SOURCE_PAGES = 10
    MAX_VIDEO_TRANSCRIPTS = 2
    MAX_ITERATIONS = 3
    SEARCH_CONCURRENCY = 3
    PAGE_VISIT_CONCURRENCY = 3
    MAX_TASKS_PER_ITERATION = 4
    MIN_CURATION_QUALITY_SCORE = 72.0
    MAX_CURATED_SOURCES_PER_TASK = 3
    MAX_CURATED_VIDEO_SOURCES_PER_TASK = 2
    MIN_CURATED_SOURCES_FOR_NOTE_COMPRESSION = 2
    MIN_DIGESTS_FOR_FULL_SYNTHESIS = 2

    def __init__(self):
        self._current_state: ResearchState | None = None
        super().__init__()

    def init_tools(self) -> None:
        self.model = get_text_model()

    def init_agent(self) -> None:
        self.planner = IterationPlanner(
            max_tasks_per_iteration=self.MAX_TASKS_PER_ITERATION,
        )
        self.collector = CollectorCurator(
            model=self.model,
            search_concurrency=self.SEARCH_CONCURRENCY,
            page_visit_concurrency=self.PAGE_VISIT_CONCURRENCY,
            max_source_pages=self.MAX_SOURCE_PAGES,
            max_video_transcripts=self.MAX_VIDEO_TRANSCRIPTS,
            min_curation_quality_score=self.MIN_CURATION_QUALITY_SCORE,
            max_curated_sources_per_task=self.MAX_CURATED_SOURCES_PER_TASK,
            max_curated_video_sources_per_task=self.MAX_CURATED_VIDEO_SOURCES_PER_TASK,
            min_curated_sources_for_note_compression=self.MIN_CURATED_SOURCES_FOR_NOTE_COMPRESSION,
        )
        self.synthesizer = SynthesizerValidator(
            model=self.model,
            chunker=self.collector.chunker,
            digestor=self.collector.digestor,
            min_source_pages=self.MIN_SOURCE_PAGES,
            min_unique_domains=self.MIN_UNIQUE_DOMAINS,
            max_iterations=self.MAX_ITERATIONS,
            min_digests_for_full_synthesis=self.MIN_DIGESTS_FOR_FULL_SYNTHESIS,
        )
        self.rules_validator = self.synthesizer.rules_validator
        self.review_validator = self.synthesizer.review_validator

    async def forward(
        self,
        topic: str,
        target_audience: str,
        strategy: ArticleStrategy,
        output_dir: Path | None = None,
    ) -> ArticleResearchResult:
        state = self.create_state(topic, target_audience, strategy, output_dir)
        with logfire.span("article_research:workflow", topic=topic, strategy=strategy.value):
            for iteration in range(self.MAX_ITERATIONS):
                with logfire.span("article_research:iteration", iteration=iteration + 1):
                    await self.step(state, iteration)
                    execution = state.current_execution
                    if execution is not None and not execution.synthesized:
                        logger.info(
                            "第 %d 轮研究增量较小，跳过全量 synthesis/review: %s",
                            iteration + 1,
                            execution.skip_reason or "low-signal iteration",
                        )
                        continue
                    validation = await self.validate(state.current_result)
                    if validation.passed:
                        self.finalize(state, iteration + 1)
                        return state.current_result
                    self.on_validation_failed(state, iteration, validation.feedback)

            logger.warning("研究审核 %d 轮全部未通过，降级使用最后一轮结果继续后续阶段", self.MAX_ITERATIONS)
            self.finalize(state, self.MAX_ITERATIONS)
            return state.current_result

    def create_state(
        self,
        topic: str,
        target_audience: str,
        strategy: ArticleStrategy,
        output_dir: Path | None,
    ) -> ResearchState:
        working_dir = output_dir or self._create_temp_output_dir(topic)
        working_dir.mkdir(parents=True, exist_ok=True)
        return ResearchState(
            topic=topic,
            target_audience=target_audience,
            strategy=strategy,
            output_dir=output_dir,
            working_dir=working_dir,
        )

    async def step(
        self,
        state: ResearchState,
        iteration: int,
    ) -> None:
        logger.info("第 %d/%d 轮长文研究", iteration + 1, self.MAX_ITERATIONS)
        state.begin_iteration(iteration + 1)
        state.current_iteration_plan = await self.planner.plan_iteration(
            state,
            iteration=iteration + 1,
        )
        state.current_execution = await self.collector.execute_iteration(
            state,
            state.current_iteration_plan.tasks,
        )
        state.aggregated_notes.extend(state.current_execution.notes)
        await self.synthesizer.prepare_iteration(state, iteration)
        save_latest_snapshot(state)
        self._current_state = state

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, ArticleResearchResult):
            return ValidationResult.failure("输出类型错误，期望 ArticleResearchResult")
        return await self.synthesizer.validate(self._current_state, output)

    def finalize(self, state: ResearchState, iteration: int) -> None:
        if state.current_result is None:
            return
        save_latest_snapshot(state)
        save_iteration_result(state, iteration)

    def on_validation_failed(self, state: ResearchState, iteration: int, feedback: str) -> None:
        if state.current_result is not None:
            state.iteration_results.append(state.current_result)
        saved_file = save_iteration_result(state, iteration + 1, validation_feedback=feedback)
        state.continuation_context = build_progress_snapshot(state, saved_file, feedback)
        save_latest_snapshot(state)
        logger.warning("第 %d 轮研究未通过验证: %s", iteration + 1, feedback)

    def _compile_task_queries(self, task: ResearchTask) -> list[str]:
        return self.collector._compile_task_queries(task)

    async def _search_candidates(
        self,
        tasks: list[ResearchTask],
        state: ResearchState,
    ) -> dict[str, list[tuple[str, SearchResult]]]:
        candidate_pool, task_candidates = await self.collector.search_candidates(tasks, state)
        execution = state.current_execution or IterationExecution()
        execution.candidate_pool = candidate_pool
        execution.task_candidates = task_candidates
        state.current_execution = execution
        return {
            task_id: [(candidate.query, candidate.result) for candidate in candidates]
            for task_id, candidates in task_candidates.items()
        }

    async def _visit_and_collect_sources(
        self,
        task: ResearchTask,
        candidates: list[tuple[str, SearchResult]] | list[QueryCandidate],
        state: ResearchState,
    ) -> list[CollectedSource]:
        query_candidates = self._coerce_query_candidates(candidates)
        execution = state.current_execution or IterationExecution()
        state.current_execution = execution
        return await self.collector.visit_and_collect_sources(
            task,
            query_candidates,
            state,
            execution=execution,
        )

    async def _collect_task_sources(
        self,
        task: ResearchTask,
        candidates: list[tuple[str, SearchResult]] | list[QueryCandidate],
        state: ResearchState,
    ) -> tuple[list[CollectedSourceCandidate], list[CollectedSource], list[str]]:
        query_candidates = self._coerce_query_candidates(candidates)
        execution = state.current_execution or IterationExecution()
        state.current_execution = execution
        return await self.collector.collect_task_sources(
            task,
            query_candidates,
            state,
            execution=execution,
        )

    def _curate_task_sources(
        self,
        task: ResearchTask,
        raw_candidates: list[CollectedSourceCandidate],
        state: ResearchState,
    ) -> tuple[list[CollectedSourceCandidate], list[str]]:
        execution = state.current_execution or IterationExecution()
        state.current_execution = execution
        return self.collector._curate_task_sources(
            task,
            raw_candidates,
            state,
            execution=execution,
        )

    def _finalize_curated_sources(
        self,
        state: ResearchState,
        curated_candidates: list[CollectedSourceCandidate],
    ) -> list[CollectedSource]:
        return self.collector._finalize_curated_sources(state, curated_candidates)

    async def _build_task_digests(
        self,
        state: ResearchState,
        sources: list[CollectedSource],
    ) -> list:
        return await self.collector._build_task_digests(state, sources)

    async def run_researcher_unit(
        self,
        *,
        state: ResearchState,
        task: ResearchTask,
        candidates: list[tuple[str, SearchResult]] | list[QueryCandidate],
    ) -> TaskAssessment:
        query_candidates = self._coerce_query_candidates(candidates)
        prioritized_candidates = self.collector._prioritize_task_candidates(task, query_candidates)
        execution = state.current_execution or IterationExecution()
        state.current_execution = execution
        raw_candidates, collected, curation_notes = await self._collect_task_sources(
            task,
            prioritized_candidates,
            state,
        )
        if collected:
            execution.collected.extend(collected)
            state.collected_sources.extend(collected)
        task_digests = await self._build_task_digests(state, collected)
        if task_digests:
            execution.digests.extend(task_digests)
        gaps = self.collector._collect_task_gaps(task, raw_candidates, collected, task_digests, curation_notes)
        return TaskAssessment(
            task_id=task.task_id,
            goal=task.goal,
            candidate_results=[item.result for item in prioritized_candidates],
            raw_source_count=len(raw_candidates),
            curated_source_count=len(collected),
            collected_source_refs=[source.ref for source in collected],
            new_digests=task_digests,
            raw_findings=self.collector._collect_raw_findings(task_digests),
            gaps=gaps,
            suggested_followups=self.collector._collect_task_followups(task, task_digests, gaps),
            curation_notes=curation_notes,
        )

    async def compress_task_result(
        self,
        task: ResearchTask,
        task_result: TaskAssessment,
    ) -> Any:
        return await self.collector.compress_task_result(task, task_result)

    async def synthesize_result(
        self,
        state: ResearchState,
        evidence_store: LocalEvidenceStore,
    ) -> ArticleResearchResult:
        return await self.synthesizer.synthesize_result(state, evidence_store)

    def _create_synthesizer(self, evidence_store: LocalEvidenceStore):
        return self.synthesizer._create_synthesizer(evidence_store)

    async def _build_local_evidence(
        self,
        *,
        state: ResearchState,
        evidence_store: LocalEvidenceStore,
    ) -> tuple[list[str], str, str]:
        return await self.synthesizer._build_local_evidence(
            state=state,
            evidence_store=evidence_store,
        )

    def _save_internal_snapshots(self, state: ResearchState) -> None:
        save_latest_snapshot(state)

    @staticmethod
    def _normalize_research_result(
        research: ArticleResearchResult,
        collected_sources: list[CollectedSource],
    ) -> None:
        SynthesizerValidator._normalize_research_result(research, collected_sources)

    @staticmethod
    def _coerce_query_candidates(
        candidates: list[tuple[str, SearchResult]] | list[QueryCandidate],
    ) -> list[QueryCandidate]:
        if not candidates:
            return []
        if isinstance(candidates[0], QueryCandidate):
            return candidates
        return [QueryCandidate(query=query, result=result) for query, result in candidates]

    @staticmethod
    def _create_temp_output_dir(topic: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in topic if c.isalnum() or c in " -_")[:24] or "article"
        return PathConfig.ARTICLE_PROJECT_DIR / "_tmp" / f"{timestamp}-{safe_topic}"
