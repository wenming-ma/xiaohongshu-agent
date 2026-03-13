"""Cross-site deep research agent for long-form articles."""

from __future__ import annotations

import json
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
from ...shared import create_shared_playwright_mcp_server
from ..schemas import (
    ArticleResearchResult,
    ArticleSource,
    ArticleStrategy,
    ArticleSourceType,
    SourceDigest,
    VideoTranscript,
)
from .prompts import (
    QUERY_PLANNER_PROMPT,
    SOURCE_DIGEST_SYSTEM_PROMPT,
    query_planner_prompt,
    source_digest_prompt,
    synthesis_system_prompt,
    synthesis_user_prompt,
)
from .state import ResearchState, build_progress_snapshot
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

    def __init__(self):
        self.init_mcp_server()
        super().__init__()

    def init_mcp_server(self) -> None:
        self.mcp_server = create_shared_playwright_mcp_server(
            output_dir=PathConfig.DOWNLOADS_DIR,
            tool_prefix="playwright",
            headless=False,
        )

    def init_tools(self) -> None:
        self.search_client = DomainSearchClient()
        self.page_reader = ArticlePageReader(self.mcp_server)
        self.video_transcriber = GenericVideoTranscriber()
        self.chunker = SourceChunker()

    def init_agent(self) -> None:
        self.model = get_text_model()
        self.query_planner = Agent(
            model=self.model,
            output_type=SearchPlan,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(QUERY_PLANNER_PROMPT,),
        )
        self.digestor = SourceDigestorAgent()

    async def forward(
        self,
        topic: str,
        target_audience: str,
        strategy: ArticleStrategy,
        output_dir: Path | None = None,
    ) -> ArticleResearchResult:
        state = self.create_state(topic, target_audience, strategy, output_dir)
        with logfire.span("article_research:workflow", topic=topic, strategy=strategy.value):
            async with self.mcp_server:
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
        search_plan_result = await self.query_planner.run(
            query_planner_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                strategy=state.strategy.value,
                continuation_context=state.continuation_context,
            )
        )
        search_plan: SearchPlan = search_plan_result.output
        if not search_plan.article_queries:
            search_plan.article_queries = [state.topic]
        if not search_plan.video_queries:
            search_plan.video_queries = [f"{state.topic} video", f"{state.topic} interview"]

        article_queries = build_site_queries(
            search_plan.article_queries[:3],
            ARTICLE_MEDIA_DOMAINS,
            max_domains_per_query=4,
            max_total_queries=12,
        )
        video_queries = build_site_queries(
            search_plan.video_queries[:2] or search_plan.article_queries[:1],
            ARTICLE_MEDIA_DOMAINS,
            max_domains_per_query=3,
            max_total_queries=6,
        )

        state.current_plan = search_plan
        candidates = await self._search_candidates(article_queries + video_queries, state)
        state.current_candidates = candidates
        collected = await self._collect_sources(candidates, state)
        state.current_collected = collected
        if collected:
            state.collected_sources.extend(collected)

        evidence_store = LocalEvidenceStore(state.working_dir or state.output_dir or Path("output"))
        evidence_files, digests_path, source_index_path = await self._build_local_evidence(
            state=state,
            evidence_store=evidence_store,
        )
        state.evidence_files = evidence_files
        state.digests_path = digests_path
        state.source_index_path = source_index_path
        payload = self._build_digest_payload(state, search_plan)
        synthesizer = self._create_synthesizer(evidence_store)

        result = await synthesizer.run(
            synthesis_user_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                requested_strategy=state.strategy.value,
                digest_payload_json=json_dumps(payload),
            )
        )
        research = result.output
        research.sources = self._build_sources(state.collected_sources)
        research.transcripts = self._build_transcripts(state.collected_sources)
        if not research.primary_source_ref and state.collected_sources:
            research.primary_source_ref = state.collected_sources[0].ref
        if state.strategy != ArticleStrategy.AUTO:
            research.suggested_strategy = state.strategy
        elif research.suggested_strategy == ArticleStrategy.AUTO:
            research.suggested_strategy = ArticleStrategy.SYNTHESIZE
        state.current_result = research
        if state.output_dir:
            logger.info(
                "第 %d 轮研究累计收集 %d 个来源到 %s",
                iteration + 1,
                len(state.collected_sources),
                state.output_dir,
            )

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, ArticleResearchResult):
            return ValidationResult.failure("研究结果类型错误")
        if output.sources_count < self.MIN_SOURCE_PAGES:
            return ValidationResult.failure(f"研究深度不足，仅收集到 {output.sources_count} 个来源")
        if output.unique_domains_count < self.MIN_UNIQUE_DOMAINS:
            return ValidationResult.failure(
                f"域名覆盖不足，仅覆盖 {output.unique_domains_count} 个域名"
            )
        if not output.claims:
            return ValidationResult.failure("研究结果缺少结构化 claims")
        if not all(claim.source_refs for claim in output.claims):
            return ValidationResult.failure("存在没有来源映射的 claim")
        if output.suggested_strategy == ArticleStrategy.REPURPOSE_VIDEO and not any(
            transcript.success for transcript in output.transcripts
        ):
            return ValidationResult.failure("视频搬运策略缺少可用转录")
        return ValidationResult.success(f"研究通过，来源数 {output.sources_count}")

    async def _search_candidates(
        self,
        queries: list[str],
        state: ResearchState,
    ) -> list[tuple[str, SearchResult]]:
        ranked: list[tuple[str, SearchResult]] = []
        for query in queries:
            results = await self.search_client.search(query, max_results=4)
            for result in results:
                if not result.url or result.url in state.seen_candidate_urls:
                    continue
                state.seen_candidate_urls.add(result.url)
                ranked.append((query, result))
        return ranked

    async def _collect_sources(
        self,
        candidates: list[tuple[str, SearchResult]],
        state: ResearchState,
    ) -> list[CollectedSource]:
        collected: list[CollectedSource] = []
        videos_used = 0

        for query, result in candidates:
            if len(state.collected_sources) + len(collected) >= self.MAX_SOURCE_PAGES:
                break

            read_result = await self.page_reader.read_page(result.url)
            if not read_result.ok:
                continue
            final_url = read_result.final_url or result.url
            if final_url in state.seen_source_urls:
                continue
            if read_result.paywall_status == "login_required" and len(read_result.text) < 1200:
                logger.info("页面受限，保留记录但不作为主来源: %s", result.url)
                continue
            if len(read_result.text) < 1200 and not is_video_candidate(result.url, read_result):
                continue

            source_type = ArticleSourceType.ARTICLE
            transcript_text = ""
            duration_seconds = 0.0

            if is_video_candidate(result.url, read_result) and videos_used < self.MAX_VIDEO_TRANSCRIPTS:
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

    def finalize(self, state: ResearchState, iteration: int) -> None:
        if state.current_result is None:
            return
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
            system_prompt=(synthesis_system_prompt(),),
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

        state.current_digests = [
            state.digests_by_source[source.ref]
            for source in state.current_collected
            if source.ref in state.digests_by_source
        ]
        all_digests = [
            state.digests_by_source[source.ref]
            for source in state.collected_sources
            if source.ref in state.digests_by_source
        ]
        digests_path = evidence_store.save_digests(all_digests)
        return evidence_files, digests_path, str(evidence_store.index_path)

    def _build_digest_payload(
        self,
        state: ResearchState,
        search_plan: SearchPlan,
    ) -> dict[str, Any]:
        return {
            "topic": state.topic,
            "target_audience": state.target_audience,
            "notes": search_plan.notes,
            "requested_strategy": state.strategy.value,
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

    @staticmethod
    def _create_temp_output_dir(topic: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in topic if c.isalnum() or c in " -_")[:24] or "article"
        return PathConfig.ARTICLE_PROJECT_DIR / "_tmp" / f"{timestamp}-{safe_topic}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
