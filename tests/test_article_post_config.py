import asyncio
import json
from pathlib import Path

from src.tools.xiaohongshu.article_post.research.agent import ResearchAgent
from src.tools.xiaohongshu.article_post.research.state import (
    CompressedResearchNote,
    ResearchBrief,
    ResearchState,
    ResearchTask,
    ResearchTaskResult,
)
from src.tools.xiaohongshu.article_post.schemas import (
    ArticleClaim,
    ArticleResearchResult,
    ArticleSource,
    ArticleSourceType,
    ArticleStrategy,
    SourceDigest,
    XHSArticlePostInput,
    XHSArticlePostOutput,
)
from src.tools.xiaohongshu.article_post.research.tools import build_site_queries
from src.tools.xiaohongshu.article_post.research.tools import (
    CollectedSource,
    LocalEvidenceStore,
    SearchPlan,
    SearchResult,
)
from src.tools.xiaohongshu.article_post.research.utils import SourceChunker, save_iteration_result


def test_article_post_input_defaults() -> None:
    data = XHSArticlePostInput(topic="capsule wardrobe", audience="25-35岁女性")

    assert data.publish is True
    assert data.generate_images is True
    assert data.strategy == ArticleStrategy.AUTO


def test_article_post_output_defaults() -> None:
    result = XHSArticlePostOutput(success=True)

    assert result.title == ""
    assert result.image_count == 0
    assert result.image_paths == []
    assert result.published is False
    assert result.output_dir == ""


def test_article_build_site_queries_caps_total_queries() -> None:
    queries = ["capsule wardrobe", "spring outfits", "linen style"]
    domains = ["allure.com", "byrdie.com", "elle.com", "vogue.com"]

    scoped = build_site_queries(
        queries,
        domains,
        max_domains_per_query=2,
        max_total_queries=5,
    )

    assert len(scoped) == 5
    assert scoped[0] == 'site:allure.com "capsule wardrobe"'
    assert scoped[1] == 'site:byrdie.com "capsule wardrobe"'
    assert scoped[2] == 'site:elle.com "spring outfits"'


def test_article_research_iteration_result_is_saved(tmp_path) -> None:
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.AUTO,
        output_dir=tmp_path,
    )
    state.brief = ResearchBrief(
        objective="形成可发布的小红书长文研究底稿",
        audience_focus="25-35岁女性",
        article_focuses=["capsule wardrobe", "spring basics"],
        video_focuses=["capsule wardrobe video"],
        must_cover=["趋势", "案例"],
        avoid_patterns=["重复 query"],
        iteration_guidance="优先补齐来源广度",
    )
    state.supervisor_iteration = 1
    state.current_plan = SearchPlan(
        article_queries=["capsule wardrobe"],
        video_queries=["capsule wardrobe video"],
        notes="focus on spring style",
    )
    state.pending_tasks = [
        ResearchTask(
            task_id="iter_1_task_1",
            goal="验证春季 capsule wardrobe 主论点",
            source_focus="article",
            article_queries=["capsule wardrobe"],
            video_queries=["capsule wardrobe video"],
            done_when="至少拿到 2 个来源",
            avoid_patterns=["重复 query"],
        )
    ]
    state.current_candidates = [
        (
            'site:allure.com "capsule wardrobe"',
            SearchResult(
                title="Capsule Wardrobe Tips",
                url="https://www.allure.com/story/capsule-wardrobe",
                snippet="A practical guide",
                domain="www.allure.com",
                rank=1,
            ),
        )
    ]
    state.current_task_candidates = {
        "iter_1_task_1": state.current_candidates[:],
    }
    state.current_collected = [
        CollectedSource(
            ref="source_1",
            url="https://www.allure.com/story/capsule-wardrobe",
            domain="www.allure.com",
            title="Capsule Wardrobe Tips",
            author="Jane Doe",
            published_at="2026-03-01",
            snippet="A practical guide",
            text="Useful spring capsule wardrobe advice.",
            headings=["Start with basics"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="search_rank=1",
            paywall_status="public",
            quality_score=88.0,
        )
    ]
    state.collected_sources = state.current_collected[:]
    state.current_digests = [
        SourceDigest(
            source_ref="source_1",
            source_type=ArticleSourceType.ARTICLE,
            url="https://www.allure.com/story/capsule-wardrobe",
            domain="www.allure.com",
            title="Capsule Wardrobe Tips",
            author="Jane Doe",
            published_at="2026-03-01",
            quality_score=88.0,
            chunk_count=1,
            summary="A concise digest.",
            key_points=["Neutral basics work well."],
        )
    ]
    state.digests_by_source = {"source_1": state.current_digests[0]}
    state.completed_task_results = [
        ResearchTaskResult(
            task_id="iter_1_task_1",
            goal="验证春季 capsule wardrobe 主论点",
            candidate_results=[state.current_candidates[0][1]],
            collected_source_refs=["source_1"],
            new_digests=state.current_digests[:],
            raw_findings=["Neutral basics work well."],
            gaps=["来源域名仍偏少"],
            suggested_followups=["capsule wardrobe expert advice"],
        )
    ]
    state.current_notes = [
        CompressedResearchNote(
            task_id="iter_1_task_1",
            summary="本轮拿到了基础 wardrobe 建议。",
            key_findings=["Neutral basics work well."],
            unresolved_gaps=["来源域名仍偏少"],
            recommended_next_queries=["capsule wardrobe expert advice"],
            source_refs=["source_1"],
        )
    ]
    state.aggregated_notes = state.current_notes[:]
    state.evidence_files = [str(tmp_path / "research_sources" / "source_1.json")]
    state.digests_path = str(tmp_path / "digests.json")
    state.source_index_path = str(tmp_path / "source_index.json")
    state.current_result = ArticleResearchResult(
        summary="A concise wardrobe research summary.",
        sources=[
            ArticleSource(
                source_ref="source_1",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.allure.com/story/capsule-wardrobe",
                domain="www.allure.com",
                title="Capsule Wardrobe Tips",
                author="Jane Doe",
                published_at="2026-03-01",
                quality_score=88.0,
            )
        ],
        claims=[
            ArticleClaim(
                claim="Neutral basics make mixing easier.",
                source_refs=["source_1"],
            )
        ],
        suggested_strategy=ArticleStrategy.SYNTHESIZE,
    )

    saved_file = save_iteration_result(state, 1, validation_feedback="need more domains")
    payload = json.loads(Path(saved_file).read_text(encoding="utf-8"))

    assert Path(saved_file).exists()
    assert payload["iteration"] == 1
    assert payload["validation_feedback"] == "need more domains"
    assert payload["brief"]["objective"] == "形成可发布的小红书长文研究底稿"
    assert payload["supervisor_iteration"] == 1
    assert payload["pending_tasks"][0]["task_id"] == "iter_1_task_1"
    assert payload["completed_task_results"][0]["task_id"] == "iter_1_task_1"
    assert payload["current_notes"][0]["task_id"] == "iter_1_task_1"
    assert payload["aggregated_notes"][0]["task_id"] == "iter_1_task_1"
    assert payload["current_task_candidates"]["iter_1_task_1"][0]["query"] == 'site:allure.com "capsule wardrobe"'
    assert payload["candidate_count"] == 1
    assert payload["new_collected_count"] == 1
    assert payload["total_collected_count"] == 1
    assert payload["digest_count"] == 1
    assert payload["digests_path"].endswith("digests.json")
    assert payload["source_index_path"].endswith("source_index.json")
    assert state.saved_files == [saved_file]


def test_article_source_chunker_splits_text_and_transcript() -> None:
    chunker = SourceChunker(max_chunk_chars=60, max_chunks=6)
    source = CollectedSource(
        ref="source_1",
        url="https://www.allure.com/story/capsule-wardrobe",
        domain="www.allure.com",
        title="Capsule Wardrobe Tips",
        author="Jane Doe",
        published_at="2026-03-01",
        snippet="A practical guide",
        text="Start with basics. Build around neutral tones. Add one statement piece for variety.",
        headings=["Start with basics"],
        source_type=ArticleSourceType.ARTICLE.value,
        engagement_hint="search_rank=1",
        paywall_status="public",
        transcript="Video explains why neutral basics reduce decision fatigue.",
    )

    chunks = chunker.chunk(source)

    assert len(chunks) >= 2
    assert chunks[0].source_ref == "source_1"
    assert any(chunk.chunk_type == "transcript" for chunk in chunks)


def test_local_evidence_store_returns_relevant_excerpt(tmp_path) -> None:
    store = LocalEvidenceStore(tmp_path)
    source = CollectedSource(
        ref="source_1",
        url="https://www.allure.com/story/capsule-wardrobe",
        domain="www.allure.com",
        title="Capsule Wardrobe Tips",
        author="Jane Doe",
        published_at="2026-03-01",
        snippet="A practical guide",
        text="Neutral basics make outfit planning easier. Add one linen blazer for spring layering.",
        headings=["Start with basics"],
        paragraphs=[
            "Neutral basics make outfit planning easier.",
            "Add one linen blazer for spring layering.",
        ],
        source_type=ArticleSourceType.ARTICLE.value,
        engagement_hint="search_rank=1",
        paywall_status="public",
    )
    digest = SourceDigest(
        source_ref="source_1",
        source_type=ArticleSourceType.ARTICLE,
        url=source.url,
        domain=source.domain,
        title=source.title,
        author=source.author,
        published_at=source.published_at,
        quality_score=88.0,
        headings=source.headings,
        chunk_count=2,
        summary="A concise digest.",
        key_points=["Neutral basics help outfit planning."],
    )

    chunks = SourceChunker(max_chunk_chars=80, max_chunks=4).chunk(source)
    store.save_sources([source], {"source_1": chunks})
    store.save_digests([digest])

    excerpt_payload = json.loads(
        asyncio.run(store.read_source_excerpt("source_1", query_hint="linen blazer", max_chunks=2))
    )
    digest_payload = json.loads(asyncio.run(store.read_source_digest("source_1")))

    assert len(excerpt_payload) == 2
    assert any("linen blazer" in item["text"].lower() for item in excerpt_payload)
    assert digest_payload["source_ref"] == "source_1"


def test_article_search_candidates_runs_concurrently_and_dedupes() -> None:
    class FakeSearchClient:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.calls: list[tuple[str, int]] = []

        async def search(self, query: str, max_results: int = 4) -> list[SearchResult]:
            self.calls.append((query, max_results))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            mapping = {
                "q1": [
                    SearchResult(
                        title="One",
                        url="https://www.allure.com/story/one",
                        snippet="one",
                        domain="www.allure.com",
                        rank=1,
                    ),
                    SearchResult(
                        title="Two",
                        url="https://www.elle.com/story/two",
                        snippet="two",
                        domain="www.elle.com",
                        rank=2,
                    ),
                ],
                "q2": [
                    SearchResult(
                        title="One Duplicate",
                        url="https://www.allure.com/story/one",
                        snippet="dup",
                        domain="www.allure.com",
                        rank=1,
                    ),
                    SearchResult(
                        title="Three",
                        url="https://www.vogue.com/story/three",
                        snippet="three",
                        domain="www.vogue.com",
                        rank=2,
                    ),
                ],
            }
            return mapping.get(query, [])

    agent = ResearchAgent.__new__(ResearchAgent)
    agent.SEARCH_CONCURRENCY = 3
    agent.search_client = FakeSearchClient()
    agent._compile_task_queries = lambda task: task.article_queries + task.video_queries

    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.AUTO,
        output_dir=None,
    )
    tasks = [
        ResearchTask(task_id="task_a", goal="A", article_queries=["q1"]),
        ResearchTask(task_id="task_b", goal="B", article_queries=["q1", "q2"]),
    ]

    task_candidates = asyncio.run(agent._search_candidates(tasks, state))

    assert len(agent.search_client.calls) == 2
    assert agent.search_client.max_active >= 2
    assert agent.search_client.max_active <= agent.SEARCH_CONCURRENCY
    assert len(state.current_candidates) == 3
    assert [result.url for _, result in task_candidates["task_a"]] == [
        "https://www.allure.com/story/one",
        "https://www.elle.com/story/two",
    ]
    assert [result.url for _, result in task_candidates["task_b"]] == [
        "https://www.allure.com/story/one",
        "https://www.elle.com/story/two",
        "https://www.vogue.com/story/three",
    ]
    assert state.seen_candidate_urls == {
        "https://www.allure.com/story/one",
        "https://www.elle.com/story/two",
        "https://www.vogue.com/story/three",
    }
