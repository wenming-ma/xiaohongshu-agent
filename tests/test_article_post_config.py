import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from src.core.base_validator import InternalValidationResult
from src.tools.xiaohongshu.article_post.content.agent import ContentAgent
from src.tools.xiaohongshu.article_post.content.state import _safe_truncate
from src.tools.xiaohongshu.article_post.publish.agent import PublisherAgent
from src.tools.xiaohongshu.article_post.publish.prompts import publish_user_prompt
from src.tools.xiaohongshu.article_post.research.agent import ResearchAgent
from src.tools.xiaohongshu.article_post.research.state import (
    CompressedResearchNote,
    ResearchBrief,
    ResearchState,
    ResearchTask,
    ResearchTaskResult,
)
from src.tools.xiaohongshu.article_post.research.validator import (
    ResearchReviewValidator,
    ResearchRulesValidator,
)
from src.tools.xiaohongshu.article_post.schemas import (
    ArticleClaim,
    ArticleBlock,
    ArticleBlockType,
    ArticleResearchResult,
    ArticleResearchReviewIssue,
    ArticleResearchReviewResult,
    ArticleSection,
    ArticleSource,
    ArticleSourceType,
    ArticleStrategy,
    ResearchDimensionReviewResult,
    ResearchReviewDimension,
    SourceDigest,
    VideoTranscript,
    XHSArticleContent,
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


def _build_valid_article_research_result(
    *,
    suggested_strategy: ArticleStrategy = ArticleStrategy.SYNTHESIZE,
    transcripts: list[VideoTranscript] | None = None,
) -> ArticleResearchResult:
    return ArticleResearchResult(
        summary="Spring wardrobe research is structured and ready for writing.",
        sources=[
            ArticleSource(
                source_ref="source_1",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.allure.com/story/spring-wardrobe",
                domain="www.allure.com",
                title="Spring Wardrobe Reset",
                author="Jane Doe",
                published_at="2026-03-01",
                quality_score=90.0,
            ),
            ArticleSource(
                source_ref="source_2",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.byrdie.com/story/linen-basics",
                domain="www.byrdie.com",
                title="Linen Basics Guide",
                author="Jane Doe",
                published_at="2026-03-02",
                quality_score=88.0,
            ),
        ],
        claims=[
            ArticleClaim(
                claim="Neutral basics and linen layers make spring outfit repetition easier.",
                source_refs=["source_1", "source_2"],
                section_hint="基础单品",
            )
        ],
        keywords=["spring wardrobe", "linen basics", "neutral layers"],
        primary_source_ref="source_1",
        suggested_strategy=suggested_strategy,
        transcripts=transcripts or [],
    )


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


def test_article_research_default_budget_supports_multi_source_validation() -> None:
    assert ResearchAgent.MIN_SOURCE_PAGES >= 2
    assert ResearchAgent.MIN_UNIQUE_DOMAINS >= 2
    assert ResearchAgent.MAX_SOURCE_PAGES >= ResearchAgent.MIN_SOURCE_PAGES
    assert ResearchAgent.MAX_ITERATIONS >= 2
    assert ResearchAgent.MAX_TASKS_PER_ITERATION >= 2


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


def test_article_research_normalizes_claims_without_source_refs() -> None:
    research = ArticleResearchResult(
        summary="French girl style myth needs deeper evidence on influencer amplification.",
        claims=[
            ArticleClaim(
                claim="战后法国时尚产业通过高定与 licensing 扩张影响全球审美。",
                source_refs=["source_1", "source_2"],
            ),
            ArticleClaim(
                claim="社交媒体时代 influencers 对法式神话的放大机制仍缺少来源支撑。",
                detail="This is a gap, not a supported claim.",
                source_refs=[],
                confidence="low",
            ),
            ArticleClaim(
                claim="部分现代品牌通过“effortless Parisian”叙事维持溢价。",
                source_refs=["source_9", "source_2", "source_2"],
            ),
        ],
        primary_source_ref="source_9",
        notes="已有历史脉络，但现代品牌样本还不够。",
        suggested_strategy=ArticleStrategy.SYNTHESIZE,
    )
    collected = [
        CollectedSource(
            ref="source_1",
            url="https://www.allure.com/story/french-style-history",
            domain="www.allure.com",
            title="French Style History",
            author="Jane Doe",
            published_at="2026-03-01",
            snippet="History of French style",
            text="French style history",
            headings=["History"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="search_rank=1",
            paywall_status="public",
        ),
        CollectedSource(
            ref="source_2",
            url="https://www.thecut.com/article/french-style-myth.html",
            domain="www.thecut.com",
            title="French Style Myth",
            author="Jane Doe",
            published_at="2026-03-02",
            snippet="Myth analysis",
            text="French style myth",
            headings=["Myth"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="search_rank=2",
            paywall_status="public",
        ),
    ]

    ResearchAgent._normalize_research_result(research, collected)

    assert len(research.claims) == 2
    assert all(claim.source_refs for claim in research.claims)
    assert research.claims[0].source_refs == ["source_1", "source_2"]
    assert research.claims[1].source_refs == ["source_2"]
    assert research.primary_source_ref == ""
    assert "未纳入 claims 的证据缺口：" in research.notes
    assert "社交媒体时代 influencers 对法式神话的放大机制仍缺少来源支撑。" in research.notes


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


def test_article_research_rules_validator_rejects_missing_depth_and_claims() -> None:
    validator = ResearchRulesValidator()
    result = ArticleResearchResult(
        summary="Need more evidence.",
        sources=[
            ArticleSource(
                source_ref="source_1",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.allure.com/story/spring-wardrobe",
                domain="www.allure.com",
                title="Spring Wardrobe Reset",
                quality_score=88.0,
            )
        ],
        claims=[],
        suggested_strategy=ArticleStrategy.SYNTHESIZE,
    )

    validation = asyncio.run(
        validator.validate(
            result,
            context={"min_source_pages": 2, "min_unique_domains": 2},
        )
    )

    assert not validation.passed
    assert "研究深度不足" in validation.feedback
    assert "域名覆盖不足" in validation.feedback
    assert "研究结果缺少结构化 claims" in validation.feedback


def test_article_research_rules_validator_rejects_invalid_refs_and_missing_video_transcript() -> None:
    validator = ResearchRulesValidator()
    result = _build_valid_article_research_result(
        suggested_strategy=ArticleStrategy.REPURPOSE_VIDEO,
    )
    result.claims = [
        ArticleClaim(
            claim="A supported claim is still missing mapped sources.",
            source_refs=[],
        ),
        ArticleClaim(
            claim="Video-led strategy needs a strong primary source.",
            source_refs=["missing_source"],
        ),
    ]

    validation = asyncio.run(
        validator.validate(
            result,
            context={"min_source_pages": 2, "min_unique_domains": 2},
        )
    )

    assert not validation.passed
    assert "存在没有来源映射的 claim" in validation.feedback
    assert "存在引用无效 source_ref 的 claim" in validation.feedback
    assert "视频搬运策略缺少可用转录" in validation.feedback


def test_article_research_rules_validator_passes_valid_result() -> None:
    validator = ResearchRulesValidator()
    result = _build_valid_article_research_result()

    validation = asyncio.run(
        validator.validate(
            result,
            context={"min_source_pages": 2, "min_unique_domains": 2},
        )
    )

    assert validation.passed
    assert validation.score == 100.0


def test_article_research_review_aggregate_respects_score_and_critical() -> None:
    warning_review = ResearchDimensionReviewResult(
        dimension=ResearchReviewDimension.TRACEABILITY,
        passed=False,
        score=85.0,
        issues=[
            ArticleResearchReviewIssue(
                dimension=ResearchReviewDimension.TRACEABILITY,
                severity="warning",
                description="主 claim 只有两个弱来源支撑。",
            )
        ],
        summary="主 claim 支撑偏弱。",
    )
    info_review = ResearchDimensionReviewResult(
        dimension=ResearchReviewDimension.DOWNSTREAM_USABILITY,
        passed=True,
        score=95.0,
        issues=[
            ArticleResearchReviewIssue(
                dimension=ResearchReviewDimension.DOWNSTREAM_USABILITY,
                severity="info",
                description="可以补充一条更强的章节提示。",
            )
        ],
        summary="可写性基本够用。",
    )
    passed_review = ResearchReviewValidator._aggregate([warning_review, info_review])

    critical_review = ResearchDimensionReviewResult(
        dimension=ResearchReviewDimension.STRATEGY_FIT,
        passed=False,
        score=60.0,
        issues=[
            ArticleResearchReviewIssue(
                dimension=ResearchReviewDimension.STRATEGY_FIT,
                severity="critical",
                description="当前结果并不支持视频搬运策略。",
            )
        ],
        summary="策略判断错误。",
    )
    failed_review = ResearchReviewValidator._aggregate([critical_review, info_review])

    assert passed_review.passed
    assert passed_review.score == 85.0
    assert not failed_review.passed
    assert failed_review.score == 70.0


def test_article_research_review_validator_registers_evidence_tools_when_index_exists(tmp_path) -> None:
    (tmp_path / "source_index.json").write_text("[]", encoding="utf-8")

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            self.tools = kwargs["tools"]

    with (
        patch("src.tools.xiaohongshu.article_post.research.validator.Agent", FakeAgent),
        patch("src.tools.xiaohongshu.article_post.research.validator.get_text_model", return_value="model"),
        patch(
            "src.tools.xiaohongshu.article_post.research.validator.LocalEvidenceStore.get_tools",
            return_value=["evidence_tool"],
        ),
    ):
        validator = ResearchReviewValidator()
        reviewers = validator._build_reviewers(tmp_path)

    reviewers_by_dimension = {
        dimension: agent.tools
        for dimension, agent in reviewers
    }
    assert reviewers_by_dimension[ResearchReviewDimension.TRACEABILITY] == ["evidence_tool"]
    assert reviewers_by_dimension[ResearchReviewDimension.SOURCE_QUALITY] == ["evidence_tool"]
    assert reviewers_by_dimension[ResearchReviewDimension.TIMELINESS_RISK] == ["evidence_tool"]
    assert reviewers_by_dimension[ResearchReviewDimension.STRATEGY_FIT] == []
    assert reviewers_by_dimension[ResearchReviewDimension.DOWNSTREAM_USABILITY] == []


def test_article_research_agent_validate_short_circuits_rules_before_review() -> None:
    class FakeRulesValidator:
        async def validate(self, result, context):
            return InternalValidationResult(False, "rules failed", 0.0)

    class FakeReviewValidator:
        last_review_result = None
        last_dimension_results = []

        async def validate(self, result, context):
            raise AssertionError("review validator should not be called")

    agent = ResearchAgent.__new__(ResearchAgent)
    agent.MIN_SOURCE_PAGES = 2
    agent.MIN_UNIQUE_DOMAINS = 2
    agent.rules_validator = FakeRulesValidator()
    agent.review_validator = FakeReviewValidator()
    agent._current_state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )

    validation = asyncio.run(agent.validate(_build_valid_article_research_result()))

    assert not validation.passed
    assert validation.feedback == "rules failed"
    assert agent._current_state.current_review_result is None
    assert agent._current_state.current_dimension_reviews == []


def test_article_research_agent_validate_updates_review_state_on_review_failure() -> None:
    issue = ArticleResearchReviewIssue(
        dimension=ResearchReviewDimension.TRACEABILITY,
        severity="warning",
        description="主 claim 还可以补一条更强来源。",
    )
    dimension_review = ResearchDimensionReviewResult(
        dimension=ResearchReviewDimension.TRACEABILITY,
        passed=False,
        score=75.0,
        issues=[issue],
        summary="主 claim 支撑偏弱。",
    )
    review_result = ArticleResearchReviewResult(
        passed=False,
        score=75.0,
        issues=[issue],
        dimension_results=[dimension_review],
        summary="研究审核未通过",
    )

    class FakeRulesValidator:
        async def validate(self, result, context):
            return InternalValidationResult(True, "", 100.0)

    class FakeReviewValidator:
        def __init__(self) -> None:
            self.last_review_result = review_result
            self.last_dimension_results = [dimension_review]

        async def validate(self, result, context):
            return InternalValidationResult(False, "review failed", 75.0)

    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.MIN_SOURCE_PAGES = 2
    agent.MIN_UNIQUE_DOMAINS = 2
    agent.rules_validator = FakeRulesValidator()
    agent.review_validator = FakeReviewValidator()
    agent._current_state = state

    validation = asyncio.run(agent.validate(_build_valid_article_research_result()))

    assert not validation.passed
    assert validation.feedback == "review failed"
    assert state.current_review_result == review_result
    assert state.current_dimension_reviews == [dimension_review]


def test_article_research_agent_validate_passes_when_rules_and_review_pass() -> None:
    review_result = ArticleResearchReviewResult(
        passed=True,
        score=92.0,
        issues=[],
        dimension_results=[],
        summary="",
    )

    class FakeRulesValidator:
        async def validate(self, result, context):
            return InternalValidationResult(True, "", 100.0)

    class FakeReviewValidator:
        def __init__(self) -> None:
            self.last_review_result = review_result
            self.last_dimension_results = []

        async def validate(self, result, context):
            return InternalValidationResult(True, "", 92.0)

    agent = ResearchAgent.__new__(ResearchAgent)
    agent.MIN_SOURCE_PAGES = 2
    agent.MIN_UNIQUE_DOMAINS = 2
    agent.rules_validator = FakeRulesValidator()
    agent.review_validator = FakeReviewValidator()
    agent._current_state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )

    validation = asyncio.run(agent.validate(_build_valid_article_research_result()))

    assert validation.passed
    assert "研究通过" in validation.feedback


def test_article_research_on_validation_failed_includes_review_feedback(tmp_path) -> None:
    issue = ArticleResearchReviewIssue(
        dimension=ResearchReviewDimension.TRACEABILITY,
        severity="warning",
        description="关键 claim 还缺一条强来源。",
    )
    dimension_review = ResearchDimensionReviewResult(
        dimension=ResearchReviewDimension.TRACEABILITY,
        passed=False,
        score=74.0,
        issues=[issue],
        summary="关键 claim 支撑偏弱。",
    )
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=tmp_path,
    )
    state.current_result = _build_valid_article_research_result()
    state.current_review_result = ArticleResearchReviewResult(
        passed=False,
        score=74.0,
        issues=[issue],
        dimension_results=[dimension_review],
        summary="研究审核未通过",
    )
    state.current_dimension_reviews = [dimension_review]

    agent = ResearchAgent.__new__(ResearchAgent)
    agent.on_validation_failed(state, 0, "review failed")

    assert "审核摘要" in state.continuation_context
    assert "关键 claim 支撑偏弱。" in state.continuation_context
    assert "关键 claim 还缺一条强来源。" in state.continuation_context


def test_article_research_internal_snapshot_writes_review_file(tmp_path) -> None:
    issue = ArticleResearchReviewIssue(
        dimension=ResearchReviewDimension.DOWNSTREAM_USABILITY,
        severity="warning",
        description="章节展开线索略少。",
    )
    dimension_review = ResearchDimensionReviewResult(
        dimension=ResearchReviewDimension.DOWNSTREAM_USABILITY,
        passed=False,
        score=78.0,
        issues=[issue],
        summary="可写性接近可用，但章节线索偏少。",
    )
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=tmp_path,
    )
    state.supervisor_iteration = 2
    state.current_review_result = ArticleResearchReviewResult(
        passed=False,
        score=78.0,
        issues=[issue],
        dimension_results=[dimension_review],
        summary="研究审核未通过",
    )
    state.current_dimension_reviews = [dimension_review]

    agent = ResearchAgent.__new__(ResearchAgent)
    agent._save_internal_snapshots(state)
    review_payload = json.loads(
        (tmp_path / "research_review_iter_02.json").read_text(encoding="utf-8")
    )

    assert review_payload["iteration"] == 2
    assert review_payload["review_result"]["score"] == 78.0
    assert review_payload["dimension_results"][0]["dimension"] == "downstream_usability"


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


def test_article_researcher_prioritizes_topical_candidates_before_collection() -> None:
    agent = ResearchAgent.__new__(ResearchAgent)

    async def fake_visit(task, candidates, state):
        return []

    async def fake_build_digests(state, collected):
        return []

    agent._visit_and_collect_sources = fake_visit
    agent._build_task_digests = fake_build_digests

    state = ResearchState(
        topic="法式穿搭神话的工业起源",
        target_audience="对时尚产业感兴趣的读者",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    task = ResearchTask(
        task_id="task_1",
        goal='探索19世纪高定时装屋如何系统化创造"法国女人"形象的商业起源',
        article_queries=[
            "haute couture Paris woman myth origin history",
            "Charles Frederick Worth French woman image creation",
        ],
    )
    candidates = [
        (
            'site:allure.com "haute couture Paris woman myth origin history"',
            SearchResult(
                title="It's Official! Dior Appoints Maria Grazia Chiuri as Artistic Director",
                url="https://www.allure.com/story/dior-appoints-maria-grazia-chiuri",
                snippet="A beauty and fashion news update.",
                domain="www.allure.com",
                rank=1,
            ),
        ),
        (
            'site:whowhatwear.com "haute couture Paris woman myth origin history"',
            SearchResult(
                title="All of the Biggest London Fashion Week SS26 Updates, Live From the Front Row",
                url="https://www.whowhatwear.com/fashion/live/london-fashion-week-spring-summer-2026",
                snippet="Street style, runway beauty, and celebrity looks.",
                domain="www.whowhatwear.com",
                rank=2,
            ),
        ),
        (
            "haute couture Paris woman myth origin history",
            SearchResult(
                title="The history of haute couture",
                url="https://www.harpersbazaar.com/uk/fashion/a31123/the-history-of-haute-couture/",
                snippet="A history of couture houses and the Paris system that made them iconic.",
                domain="www.harpersbazaar.com",
                rank=3,
            ),
        ),
        (
            "Charles Frederick Worth French woman image creation",
            SearchResult(
                title="Charles Frederick Worth (1825–1895) and the House of Worth",
                url="https://www.metmuseum.org/essays/charles-frederick-worth-1825-1895-and-the-house-of-worth",
                snippet="The Met outlines how Worth helped establish haute couture in Paris.",
                domain="www.metmuseum.org",
                rank=4,
            ),
        ),
    ]

    task_result = asyncio.run(agent.run_researcher_unit(state=state, task=task, candidates=candidates))
    prioritized_urls = [result.url for result in task_result.candidate_results]

    assert set(prioritized_urls[:2]) == {
        "https://www.harpersbazaar.com/uk/fashion/a31123/the-history-of-haute-couture/",
        "https://www.metmuseum.org/essays/charles-frederick-worth-1825-1895-and-the-house-of-worth",
    }
    assert prioritized_urls[-2:] == [
        "https://www.allure.com/story/dior-appoints-maria-grazia-chiuri",
        "https://www.whowhatwear.com/fashion/live/london-fashion-week-spring-summer-2026",
    ]


def test_article_content_history_drops_tool_messages_with_tool_call_ids() -> None:
    history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[ToolCallPart(tool_name="list_sources", args={}, tool_call_id="call_1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="list_sources", content="[]", tool_call_id="call_1")]),
        ModelRequest(parts=[RetryPromptPart(content="retry", tool_name="read_excerpt", tool_call_id="call_2")]),
        ModelResponse(parts=[TextPart(content="修订稿")]),
    ]

    filtered = _safe_truncate(history, 10)

    assert filtered == [history[0], history[4]]


def test_article_content_normalizes_missing_source_refs_for_synthesize() -> None:
    research = ArticleResearchResult(
        sources=[
            ArticleSource(
                source_ref="source_1",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.allure.com/story/spring-style",
                domain="www.allure.com",
                title="Spring Style Reset",
                quality_score=90.0,
            ),
            ArticleSource(
                source_ref="source_2",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.byrdie.com/story/linen-basics",
                domain="www.byrdie.com",
                title="Linen Basics Guide",
                quality_score=88.0,
            ),
            ArticleSource(
                source_ref="source_3",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.elle.com/story/soft-tailoring",
                domain="www.elle.com",
                title="Soft Tailoring Update",
                quality_score=86.0,
            ),
        ],
        claims=[
            ArticleClaim(
                claim="春季衣橱的核心是轻薄分层和可重复搭配。",
                detail="Linen basics and soft tailoring help reduce outfit fatigue.",
                source_refs=["source_1", "source_2"],
                section_hint="基础单品",
            ),
            ArticleClaim(
                claim="柔和剪裁能让通勤装更松弛。",
                detail="Soft tailoring is replacing rigid office dressing.",
                source_refs=["source_2", "source_3"],
                section_hint="通勤变化",
            ),
        ],
        suggested_strategy=ArticleStrategy.SYNTHESIZE,
    )
    content = XHSArticleContent(
        strategy=ArticleStrategy.SYNTHESIZE,
        title="春季衣橱重启的实用思路",
        lead="这篇长文把春季衣橱里最值得投入的单品和搭配逻辑拆开讲清楚，方便直接照着整理。",
        sections=[
            ArticleSection(
                heading="基础单品先定下来",
                summary="先把最常穿、最容易重复搭配的单品列清楚。",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="Linen basics 和轻薄外套是今年最稳的起点。",
                    )
                ],
            ),
            ArticleSection(
                heading="通勤变化别太用力",
                summary="柔和剪裁比硬挺正装更适合现在的办公室氛围。",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="Soft tailoring 让通勤装看起来更松弛，也更容易从办公室切到下班场景。",
                    )
                ],
            ),
            ArticleSection(
                heading="最后再补配色和层次",
                summary="配色和层次决定衣橱到底耐不耐看。",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.BULLET_LIST,
                        items=["先定中性色", "再补一件有存在感的轻外套"],
                    )
                ],
            ),
        ],
        closing="按这个顺序整理，衣橱会比一口气乱买更稳定。",
        hashtags=["春季穿搭", "衣橱整理", "通勤搭配", "基础单品"],
    )

    ContentAgent._normalize_source_refs(content, research)

    valid_refs = {"source_1", "source_2", "source_3"}
    assert all(len(section.source_refs) >= 2 for section in content.sections)
    assert all(set(section.source_refs) <= valid_refs for section in content.sections)
    assert all(section.source_refs for section in content.sections)
    for section in content.sections:
        for block in section.blocks:
            assert len(block.source_refs) >= 2
            assert set(block.source_refs) <= valid_refs


def test_article_publish_image_plan_follows_image_slots(tmp_path) -> None:
    content = XHSArticleContent(
        title="春季胶囊衣橱怎么搭更省心",
        lead="这篇长文会把春季胶囊衣橱的单品、搭配顺序和预算分配拆开讲清楚，方便直接照着执行。",
        sections=[
            ArticleSection(
                heading="先把高频单品定下来",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="第一步先把白衬衫、针织和轻外套这些高频单品固定下来。",
                    ),
                    ArticleBlock(
                        block_type=ArticleBlockType.IMAGE_SLOT,
                        image_key="cover",
                    ),
                ],
            ),
            ArticleSection(
                heading="再补通勤场景的变化",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="柔和剪裁和低饱和配色会让通勤穿搭看起来更松弛。",
                    ),
                    ArticleBlock(
                        block_type=ArticleBlockType.IMAGE_SLOT,
                        image_key="section_2",
                    ),
                ],
            ),
        ],
        closing="按这个顺序整理，衣橱会更稳定，也更容易重复搭配。",
    )
    images = [
        tmp_path / "cover.png",
        tmp_path / "section_2.png",
    ]

    plan = PublisherAgent._build_image_plan(content, images)

    assert "cover:" in plan
    assert "section_2:" in plan
    assert "《先把高频单品定下来》" in plan
    assert "《再补通勤场景的变化》" in plan
    assert "第一段前" in plan
    assert "之后插入" in plan


def test_article_publish_prompt_mentions_toolbar_image_flow(tmp_path) -> None:
    prompt = publish_user_prompt(
        title="测试标题",
        body="第一段\n第二段",
        hashtags="无",
        images=f"1. cover: {tmp_path / 'cover.png'}",
        image_plan=f"1. cover: {tmp_path / 'cover.png'} -> 在章节《测试》开头附近插入。",
    )

    assert "图片插入计划" in prompt
    assert "cover:" in prompt
    assert "逐张上传" in prompt
