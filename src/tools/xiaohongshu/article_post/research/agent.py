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

from .....config.settings import PathConfig, RetryConfig
from .....core.base_agent import BaseAgent, ValidationResult
from .....utils.logger import get_logger
from .....utils.providers import get_text_model
from ..schemas import (
    ArticleResearchResult,
    ArticleSource,
    ArticleStrategy,
    ArticleSourceType,
    SourceDigest,
    VideoTranscript,
)
from .prompts import (
    RESEARCH_BRIEF_SYSTEM_PROMPT,
    SOURCE_DIGEST_SYSTEM_PROMPT,
    SUPERVISOR_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    TASK_NOTE_SYSTEM_PROMPT,
    research_brief_prompt,
    source_digest_prompt,
    supervisor_prompt,
    synthesis_user_prompt,
    task_note_prompt,
)
from .state import (
    CompressedResearchNote,
    ResearchBrief,
    ResearchState,
    ResearchTask,
    ResearchTaskResult,
    SupervisorPlan,
    build_progress_snapshot,
)
from .tools import (
    ARTICLE_MEDIA_DOMAINS,
    ArticlePageReader,
    CollectedSource,
    DomainSearchClient,
    GenericVideoTranscriber,
    LocalEvidenceStore,
    SearchPlan,
    SearchResult,
    build_site_queries,
    is_article_media_domain,
    is_video_candidate,
    score_candidate,
    select_best_video_url,
)
from .utils import SourceChunker, save_iteration_result
from .validator import ResearchReviewValidator, ResearchRulesValidator

logger = get_logger(__name__)


class SourceDigestDraft(BaseModel):
    summary: str = ""
    key_points: list[str] = Field(default_factory=list, max_length=5)
    evidence_queries: list[str] = Field(default_factory=list, max_length=4)
    risk_notes: str = ""


class SourceDigestorAgent:
    def __init__(self):
        self._agent = Agent(
            model=get_text_model(),
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
        chunks: list,
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
                source_json=json.dumps(payload, ensure_ascii=False, indent=2),
                chunks_json=json.dumps(chunk_payload, ensure_ascii=False, indent=2),
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


class ResearchAgent(BaseAgent):
    role = "跨站深度研究员"
    goal = "从海外高质量女性向媒体中提取高价值文章和视频信息"

    MIN_SOURCE_PAGES = 8
    MIN_UNIQUE_DOMAINS = 6
    MAX_SOURCE_PAGES = 10
    MAX_VIDEO_TRANSCRIPTS = 2
    MAX_ITERATIONS = 13
    SEARCH_CONCURRENCY = 3
    MAX_TASKS_PER_ITERATION = 4

    def __init__(self):
        self._current_state: ResearchState | None = None
        super().__init__()
        self.init_validators()

    def init_tools(self) -> None:
        self.search_client = DomainSearchClient()
        self.page_reader = ArticlePageReader()
        self.video_transcriber = GenericVideoTranscriber()
        self.chunker = SourceChunker()

    def init_agent(self) -> None:
        self.model = get_text_model()
        self.brief_builder = Agent(
            model=self.model,
            output_type=ResearchBrief,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(RESEARCH_BRIEF_SYSTEM_PROMPT,),
        )
        self.supervisor = Agent(
            model=self.model,
            output_type=SupervisorPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(SUPERVISOR_SYSTEM_PROMPT,),
        )
        self.note_compressor = Agent(
            model=self.model,
            output_type=CompressedResearchNote,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(TASK_NOTE_SYSTEM_PROMPT,),
        )
        self.digestor = SourceDigestorAgent()

    def init_validators(self) -> None:
        self.rules_validator = ResearchRulesValidator()
        self.review_validator = ResearchReviewValidator()

    async def forward(
        self,
        topic: str,
        target_audience: str,
        strategy: ArticleStrategy,
        output_dir: Path | None = None,
    ) -> ArticleResearchResult:
        state = self.create_state(topic, target_audience, strategy, output_dir)
        with logfire.span("article_research:workflow", topic=topic, strategy=strategy.value):
            last_feedback = "研究未完成"
            for iteration in range(self.MAX_ITERATIONS):
                with logfire.span("article_research:iteration", iteration=iteration + 1):
                    await self.step(state, iteration)
                    validation = await self.validate(state.current_result)
                    if validation.passed:
                        self.finalize(state, iteration + 1)
                        return state.current_result
                    last_feedback = validation.feedback
                    self.on_validation_failed(state, iteration, validation.feedback)

            raise RuntimeError(last_feedback)

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
        state.supervisor_iteration = iteration + 1
        state.current_candidates = []
        state.current_task_candidates = {}
        state.current_collected = []
        state.current_digests = []
        state.current_notes = []
        state.completed_task_results = []
        state.current_review_result = None
        state.current_dimension_reviews = []

        state.brief = await self.build_research_brief(state)
        plan = await self.run_supervisor_iteration(state, iteration)
        state.pending_tasks = plan.tasks
        state.current_plan = self._build_iteration_search_plan(plan, state.brief)
        state.current_task_candidates = await self._search_candidates(plan.tasks, state)

        for task in plan.tasks:
            task_result = await self.run_researcher_unit(
                state=state,
                task=task,
                candidates=state.current_task_candidates.get(task.task_id, []),
            )
            state.completed_task_results.append(task_result)
            note = await self.compress_task_result(task, task_result)
            state.current_notes.append(note)

        state.aggregated_notes.extend(state.current_notes)
        self._save_internal_snapshots(state)

        evidence_store = LocalEvidenceStore(state.working_dir or state.output_dir or Path("output"))
        state.current_result = await self.synthesize_result(state, evidence_store)
        if state.output_dir:
            logger.info(
                "第 %d 轮研究累计收集 %d 个来源到 %s",
                iteration + 1,
                len(state.collected_sources),
                state.output_dir,
            )
        self._current_state = state

    async def build_research_brief(self, state: ResearchState) -> ResearchBrief:
        try:
            result = await self.brief_builder.run(
                research_brief_prompt(
                    topic=state.topic,
                    target_audience=state.target_audience,
                    requested_strategy=state.strategy.value,
                    continuation_context=state.continuation_context,
                )
            )
            brief = result.output
        except Exception as exc:
            logger.warning("研究 brief 生成失败，使用回退方案: %s", exc)
            brief = ResearchBrief()
        return self._normalize_brief(state, brief)

    async def run_supervisor_iteration(
        self,
        state: ResearchState,
        iteration: int,
    ) -> SupervisorPlan:
        brief = state.brief or self._fallback_brief(state)
        notes_payload = [
            note.model_dump(mode="json")
            for note in state.aggregated_notes[-6:]
        ]
        try:
            result = await self.supervisor.run(
                supervisor_prompt(
                    topic=state.topic,
                    target_audience=state.target_audience,
                    requested_strategy=state.strategy.value,
                    brief_json=json_dumps(brief.model_dump(mode="json")),
                    notes_json=json_dumps(notes_payload),
                    continuation_context=state.continuation_context,
                )
            )
            plan = result.output
        except Exception as exc:
            logger.warning("研究任务拆解失败，使用回退任务: %s", exc)
            plan = SupervisorPlan()
        return self._normalize_supervisor_plan(state, brief, plan, iteration)

    async def validate(self, output: Any) -> ValidationResult:
        state = self._current_state
        rules_result = await self.rules_validator.validate(
            output,
            context={
                "min_source_pages": self.MIN_SOURCE_PAGES,
                "min_unique_domains": self.MIN_UNIQUE_DOMAINS,
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

    async def _search_candidates(
        self,
        tasks: list[ResearchTask],
        state: ResearchState,
    ) -> dict[str, list[tuple[str, SearchResult]]]:
        query_to_tasks: dict[str, list[str]] = {}
        for task in tasks:
            for query in self._compile_task_queries(task):
                query_to_tasks.setdefault(query, [])
                if task.task_id not in query_to_tasks[query]:
                    query_to_tasks[query].append(task.task_id)

        if not query_to_tasks:
            state.current_candidates = []
            return {}

        sem = asyncio.Semaphore(self.SEARCH_CONCURRENCY)

        async def _run(query: str) -> tuple[str, list[SearchResult]]:
            async with sem:
                return query, await self.search_client.search(query, max_results=4)

        pairs = await asyncio.gather(*[_run(query) for query in query_to_tasks])

        result_by_url: dict[str, tuple[str, SearchResult]] = {}
        task_urls: dict[str, list[str]] = {task.task_id: [] for task in tasks}

        for query, results in pairs:
            for result in results:
                if not result.url or result.url in state.seen_candidate_urls:
                    continue
                if result.url not in result_by_url:
                    result_by_url[result.url] = (query, result)
                for task_id in query_to_tasks.get(query, []):
                    task_urls.setdefault(task_id, []).append(result.url)

        for url in result_by_url:
            state.seen_candidate_urls.add(url)

        task_candidates: dict[str, list[tuple[str, SearchResult]]] = {}
        for task in tasks:
            seen_urls: set[str] = set()
            task_candidates[task.task_id] = []
            for url in task_urls.get(task.task_id, []):
                if url in seen_urls or url not in result_by_url:
                    continue
                seen_urls.add(url)
                task_candidates[task.task_id].append(result_by_url[url])

        state.current_candidates = list(result_by_url.values())
        return task_candidates

    async def run_researcher_unit(
        self,
        *,
        state: ResearchState,
        task: ResearchTask,
        candidates: list[tuple[str, SearchResult]],
    ) -> ResearchTaskResult:
        prioritized_candidates = self._prioritize_task_candidates(task, candidates)
        collected = await self._visit_and_collect_sources(task, prioritized_candidates, state)
        if collected:
            state.current_collected.extend(collected)
            state.collected_sources.extend(collected)

        task_digests = await self._build_task_digests(state, collected)
        if task_digests:
            state.current_digests.extend(task_digests)

        raw_findings = self._collect_raw_findings(task_digests)
        gaps = self._collect_task_gaps(task, collected, task_digests)
        followups = self._collect_task_followups(task, task_digests, gaps)
        return ResearchTaskResult(
            task_id=task.task_id,
            goal=task.goal,
            candidate_results=[result for _, result in prioritized_candidates],
            collected_source_refs=[source.ref for source in collected],
            new_digests=task_digests,
            raw_findings=raw_findings,
            gaps=gaps,
            suggested_followups=followups,
        )

    async def compress_task_result(
        self,
        task: ResearchTask,
        task_result: ResearchTaskResult,
    ) -> CompressedResearchNote:
        if not task_result.collected_source_refs:
            return CompressedResearchNote(
                task_id=task.task_id,
                summary=f"{task.goal or task.task_id} 暂未找到可用来源",
                unresolved_gaps=task_result.gaps[:4],
                recommended_next_queries=task_result.suggested_followups[:4],
                source_refs=[],
            )

        try:
            result = await self.note_compressor.run(
                task_note_prompt(
                    task_json=json_dumps(task.model_dump(mode="json")),
                    result_json=json_dumps(task_result.model_dump(mode="json")),
                    digests_json=json_dumps(
                        [digest.model_dump(mode="json") for digest in task_result.new_digests]
                    ),
                )
            )
            note = result.output
        except Exception as exc:
            logger.warning("研究任务 notes 压缩失败，使用回退结果: %s", exc)
            note = CompressedResearchNote(task_id=task.task_id)
        return self._normalize_task_note(task, task_result, note)

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
                brief_json=json_dumps(
                    (state.brief or self._fallback_brief(state)).model_dump(mode="json")
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

    async def _visit_and_collect_sources(
        self,
        task: ResearchTask,
        candidates: list[tuple[str, SearchResult]],
        state: ResearchState,
    ) -> list[CollectedSource]:
        collected: list[CollectedSource] = []
        videos_used = sum(1 for source in state.collected_sources if source.transcript)
        wants_video = "video" in (task.source_focus or "").lower() or state.strategy == ArticleStrategy.REPURPOSE_VIDEO

        for query, result in candidates:
            # Per-iteration cap: allow each iteration to collect up to MAX_SOURCE_PAGES
            # new sources so subsequent iterations can improve domain diversity.
            if len(state.current_collected) + len(collected) >= self.MAX_SOURCE_PAGES:
                break

            read_result = await self.page_reader.read_page(result.url)
            if not read_result.ok:
                logger.warning("跳过(提取失败): %s notes=%s", result.url, read_result.notes[:120])
                continue
            final_url = read_result.final_url or result.url
            if final_url in state.seen_source_urls:
                logger.info("跳过(已访问): %s", final_url)
                continue
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
                video_url = select_best_video_url(read_result)
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

            quality_score = score_candidate(
                result,
                read_result,
                wants_video=source_type != ArticleSourceType.ARTICLE,
            )
            ref = f"source_{len(state.collected_sources) + len(collected) + 1}"
            collected.append(
                CollectedSource(
                    ref=ref,
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
                    engagement_hint=read_result.engagement_hint or f"search_rank={result.rank} query={query[:80]}",
                    paywall_status=read_result.paywall_status,
                    quality_score=quality_score,
                    transcript=transcript_text,
                    duration_seconds=duration_seconds,
                )
            )
            state.seen_source_urls.add(final_url)

        return collected

    @classmethod
    def _prioritize_task_candidates(
        cls,
        task: ResearchTask,
        candidates: list[tuple[str, SearchResult]],
    ) -> list[tuple[str, SearchResult]]:
        return [
            candidate
            for _, candidate in sorted(
                enumerate(candidates),
                key=lambda item: (
                    cls._score_task_candidate(task, item[1][0], item[1][1]),
                    -(item[1][1].rank or 0),
                ),
                reverse=True,
            )
        ]

    @classmethod
    def _score_task_candidate(
        cls,
        task: ResearchTask,
        query: str,
        result: SearchResult,
    ) -> float:
        terms = cls._extract_relevance_terms(
            task.goal,
            *task.article_queries,
            *task.video_queries,
        )
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
            "about",
            "after",
            "article",
            "articles",
            "balanced",
            "could",
            "image",
            "into",
            "media",
            "paris",
            "parisian",
            "style",
            "their",
            "these",
            "they",
            "this",
            "video",
            "videos",
            "what",
            "when",
            "which",
            "with",
            "woman",
            "women",
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

    def finalize(self, state: ResearchState, iteration: int) -> None:
        if state.current_result is None:
            return
        self._save_internal_snapshots(state)
        save_iteration_result(state, iteration)

    def on_validation_failed(self, state: ResearchState, iteration: int, feedback: str) -> None:
        if state.current_result is not None:
            state.iteration_results.append(state.current_result)
        saved_file = save_iteration_result(state, iteration + 1, validation_feedback=feedback)
        state.continuation_context = build_progress_snapshot(
            state,
            saved_file,
            feedback,
        )
        logger.warning("第 %d 轮研究未通过验证: %s", iteration + 1, feedback)

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
                    duration_seconds=item.duration_seconds if item.source_type != ArticleSourceType.ARTICLE.value else 0.0,
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
            gap_summary = "；".join(ResearchAgent._unique_keep_order(dropped_claim_notes)[:4])
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
        return {
            "topic": state.topic,
            "target_audience": state.target_audience,
            "requested_strategy": state.strategy.value,
            "brief": (
                state.brief.model_dump(mode="json")
                if state.brief is not None
                else self._fallback_brief(state).model_dump(mode="json")
            ),
            "notes": [note.model_dump(mode="json") for note in state.aggregated_notes[-12:]],
            "current_iteration_notes": [
                note.model_dump(mode="json") for note in state.current_notes
            ],
            "task_results": [
                {
                    "task_id": result.task_id,
                    "goal": result.goal,
                    "source_refs": result.collected_source_refs,
                    "gaps": result.gaps,
                    "suggested_followups": result.suggested_followups,
                }
                for result in state.completed_task_results
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

    def _build_iteration_search_plan(
        self,
        plan: SupervisorPlan,
        brief: ResearchBrief,
    ) -> SearchPlan:
        article_queries = self._unique_keep_order(
            query
            for task in plan.tasks
            for query in task.article_queries
            if query.strip()
        )
        video_queries = self._unique_keep_order(
            query
            for task in plan.tasks
            for query in task.video_queries
            if query.strip()
        )
        return SearchPlan(
            article_queries=article_queries[:8],
            video_queries=video_queries[:6],
            notes=brief.objective or plan.summary,
        )

    def _compile_task_queries(self, task: ResearchTask) -> list[str]:
        article_seed = [item.strip() for item in task.article_queries if item.strip()]
        video_seed = [item.strip() for item in task.video_queries if item.strip()]
        goal_seed = task.goal.strip() if task.goal.strip() else "women lifestyle trend"
        if not article_seed:
            article_seed = [goal_seed]
        if not video_seed:
            video_seed = [f"{goal_seed} interview"]

        article_queries = build_site_queries(
            article_seed[:2],
            ARTICLE_MEDIA_DOMAINS,
            max_domains_per_query=2,
            max_total_queries=4,
        )
        video_queries = build_site_queries(
            video_seed[:1],
            ARTICLE_MEDIA_DOMAINS,
            max_domains_per_query=2,
            max_total_queries=2,
        )
        # Open-web fallback queries (no site: constraint) ensure that topics
        # with academic/scientific angles still find relevant content even when
        # domain-scoped exact-phrase searches return 0 results.
        open_queries = [q for q in article_seed[:2] if q]
        if "video" in task.source_focus.lower():
            return video_queries + article_queries + open_queries
        return article_queries + video_queries + open_queries

    def _normalize_brief(self, state: ResearchState, brief: ResearchBrief) -> ResearchBrief:
        article_focuses = self._clean_list(
            brief.article_focuses,
            fallback=[state.topic, f"{state.topic} trend"],
            limit=4,
        )
        video_focuses = self._clean_list(
            brief.video_focuses,
            fallback=[f"{state.topic} interview", f"{state.topic} video"],
            limit=3,
        )
        must_cover = self._clean_list(
            brief.must_cover,
            fallback=["跨域名来源", "关键 claims 证据", "可用视频补证"],
            limit=5,
        )
        avoid_patterns = self._clean_list(
            brief.avoid_patterns,
            fallback=["重复 query", "重复来源", "重复 claim"],
            limit=4,
        )
        objective = brief.objective.strip() or f"围绕 {state.topic} 形成可发布的小红书长文研究底稿"
        audience_focus = brief.audience_focus.strip() or state.target_audience
        iteration_guidance = brief.iteration_guidance.strip() or "优先补齐来源广度和 claim 支撑"
        return ResearchBrief(
            objective=objective,
            audience_focus=audience_focus,
            article_focuses=article_focuses,
            video_focuses=video_focuses,
            must_cover=must_cover,
            avoid_patterns=avoid_patterns,
            iteration_guidance=iteration_guidance,
        )

    def _fallback_brief(self, state: ResearchState) -> ResearchBrief:
        return self._normalize_brief(state, ResearchBrief())

    def _normalize_supervisor_plan(
        self,
        state: ResearchState,
        brief: ResearchBrief,
        plan: SupervisorPlan,
        iteration: int,
    ) -> SupervisorPlan:
        normalized_tasks: list[ResearchTask] = []
        fallback_tasks = self._fallback_tasks(state, brief)
        candidates = plan.tasks or fallback_tasks
        for idx, task in enumerate(candidates[: self.MAX_TASKS_PER_ITERATION], start=1):
            article_queries = self._clean_list(
                task.article_queries,
                fallback=brief.article_focuses[:2],
                limit=3,
            )
            video_queries = self._clean_list(
                task.video_queries,
                fallback=brief.video_focuses[:1],
                limit=2,
            )
            fallback_goal = brief.must_cover[min(idx - 1, len(brief.must_cover) - 1)]
            goal = task.goal.strip() or fallback_goal
            source_focus = task.source_focus.strip() or "balanced"
            done_when = task.done_when.strip() or "拿到至少 2 个可用来源并形成可复用结论"
            avoid_patterns = self._clean_list(
                task.avoid_patterns,
                fallback=brief.avoid_patterns,
                limit=4,
            )
            normalized_tasks.append(
                ResearchTask(
                    task_id=task.task_id.strip() or f"iter_{iteration + 1}_task_{idx}",
                    goal=goal,
                    source_focus=source_focus,
                    article_queries=article_queries,
                    video_queries=video_queries,
                    done_when=done_when,
                    avoid_patterns=avoid_patterns,
                )
            )
        if not normalized_tasks:
            normalized_tasks = self._fallback_tasks(state, brief)
            for idx, task in enumerate(normalized_tasks, start=1):
                task.task_id = f"iter_{iteration + 1}_task_{idx}"
        summary = plan.summary.strip() or brief.objective
        return SupervisorPlan(summary=summary, tasks=normalized_tasks)

    def _fallback_tasks(
        self,
        state: ResearchState,
        brief: ResearchBrief,
    ) -> list[ResearchTask]:
        primary_query = brief.article_focuses[0] if brief.article_focuses else state.topic
        secondary_query = brief.article_focuses[1] if len(brief.article_focuses) > 1 else f"{state.topic} expert advice"
        video_query = brief.video_focuses[0] if brief.video_focuses else f"{state.topic} interview"
        return [
            ResearchTask(
                goal=brief.must_cover[0] if brief.must_cover else f"{state.topic} 趋势与主论点",
                source_focus="article",
                article_queries=[primary_query, secondary_query],
                video_queries=[],
                done_when="拿到 3 个以上高质量文章来源",
                avoid_patterns=brief.avoid_patterns[:4],
            ),
            ResearchTask(
                goal=brief.must_cover[1] if len(brief.must_cover) > 1 else f"{state.topic} 视频补证与案例",
                source_focus="video" if state.strategy == ArticleStrategy.REPURPOSE_VIDEO else "mixed",
                article_queries=[secondary_query],
                video_queries=[video_query],
                done_when="补齐 1 个以上可转录视频或补充案例来源",
                avoid_patterns=brief.avoid_patterns[:4],
            ),
        ]

    def _normalize_task_note(
        self,
        task: ResearchTask,
        task_result: ResearchTaskResult,
        note: CompressedResearchNote,
    ) -> CompressedResearchNote:
        summary = note.summary.strip() or (
            task_result.raw_findings[0] if task_result.raw_findings else f"{task.goal} 新增信息有限"
        )
        key_findings = self._clean_list(note.key_findings, fallback=task_result.raw_findings, limit=5)
        unresolved_gaps = self._clean_list(
            note.unresolved_gaps,
            fallback=task_result.gaps,
            limit=4,
        )
        recommended_next_queries = self._clean_list(
            note.recommended_next_queries,
            fallback=task_result.suggested_followups,
            limit=4,
        )
        source_refs = self._clean_list(
            note.source_refs,
            fallback=task_result.collected_source_refs,
            limit=8,
        )
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
        return self._unique_keep_order(findings)[:8]

    def _collect_task_gaps(
        self,
        task: ResearchTask,
        collected: list[CollectedSource],
        digests: list[SourceDigest],
    ) -> list[str]:
        gaps: list[str] = []
        if not collected:
            gaps.append("未找到可用主来源")
        if "video" in task.source_focus.lower() and not any(source.transcript for source in collected):
            gaps.append("缺少可用视频转录")
        if len({source.domain for source in collected}) < 2:
            gaps.append("来源域名仍偏少")
        if not any(digest.key_points for digest in digests):
            gaps.append("高价值结论仍不够明确")
        return self._unique_keep_order(gaps)[:4]

    def _collect_task_followups(
        self,
        task: ResearchTask,
        digests: list[SourceDigest],
        gaps: list[str],
    ) -> list[str]:
        followups: list[str] = []
        for digest in digests:
            followups.extend(item.strip() for item in digest.evidence_queries if item.strip())
        if not followups and gaps:
            followups.extend(task.article_queries[:2])
            followups.extend(task.video_queries[:1])
        return self._unique_keep_order(followups)[:4]

    def _save_internal_snapshots(self, state: ResearchState) -> None:
        output_dir = state.working_dir or state.output_dir
        if output_dir is None:
            return
        self._write_json(
            output_dir / "research_brief.json",
            state.brief.model_dump(mode="json") if state.brief else {},
        )
        self._write_json(
            output_dir / "research_notes.json",
            [note.model_dump(mode="json") for note in state.aggregated_notes],
        )
        if state.pending_tasks:
            self._write_json(
                output_dir / f"research_tasks_iter_{state.supervisor_iteration:02d}.json",
                {
                    "iteration": state.supervisor_iteration,
                    "tasks": [task.model_dump(mode="json") for task in state.pending_tasks],
                    "task_results": [
                        result.model_dump(mode="json") for result in state.completed_task_results
                    ],
                },
            )
        if state.current_review_result is not None:
            self._write_json(
                output_dir / f"research_review_iter_{state.supervisor_iteration:02d}.json",
                {
                    "iteration": state.supervisor_iteration,
                    "review_result": state.current_review_result.model_dump(mode="json"),
                    "dimension_results": [
                        item.model_dump(mode="json") for item in state.current_dimension_reviews
                    ],
                },
            )

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _clean_list(
        values: list[str],
        *,
        fallback: list[str],
        limit: int,
    ) -> list[str]:
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        if not cleaned:
            cleaned = [str(item).strip() for item in fallback if str(item).strip()]
        seen: set[str] = set()
        result: list[str] = []
        for item in cleaned:
            lowered = item.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(item)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _unique_keep_order(values: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw in values:
            value = str(raw).strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(value)
        return result

    @staticmethod
    def _create_temp_output_dir(topic: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in topic if c.isalnum() or c in " -_")[:24] or "article"
        return PathConfig.ARTICLE_PROJECT_DIR / "_tmp" / f"{timestamp}-{safe_topic}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
