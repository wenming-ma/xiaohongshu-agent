import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from src.core.base_agent import ValidationResult
from src.core.base_validator import InternalValidationResult
from src.agents.article_post.content.agent import ContentAgent
from src.agents.article_post.content.prompts import content_revision_user_prompt
from src.agents.article_post.content.state import ContentState
from src.agents.article_post.image.agent import ImageAgent
from src.agents.article_post.image.prompts import image_system_prompt, image_user_prompt
from src.agents.article_post.research.agent import ResearchAgent
from src.agents.article_post.research.state import (
    CompressedResearchNote,
    IterationExecution,
    IterationPlan,
    QueryCandidate,
    ResearchState,
    ResearchTask,
    ResearchTaskResult,
)
from src.agents.article_post.research.validator import (
    ResearchReviewValidator,
    ResearchRulesValidator,
)
from src.agents.article_post.schemas import (
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
)
from src.agents.article_post.research.tools import build_site_queries
from src.agents.article_post.research.tools import (
    CollectedSource,
    CollectedSourceCandidate,
    DomainSearchClient,
    LocalEvidenceStore,
    ReadPageResult,
    SearchResult,
    TranscriptResult,
)
from src.agents.article_post.utils.research import (
    SourceChunker,
    save_iteration_result,
    save_latest_snapshot,
)


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
    state.begin_iteration(1)
    state.current_iteration_plan = IterationPlan(
        objective="形成可发布的小红书长文研究底稿",
        audience_focus="25-35岁女性",
        tasks=[
            ResearchTask(
                task_id="iter_1_task_1",
                goal="验证春季 capsule wardrobe 主论点",
                source_focus="article",
                article_queries=["capsule wardrobe"],
                video_queries=["capsule wardrobe video"],
                done_when="至少拿到 2 个来源",
                avoid_patterns=["重复 query"],
            )
        ],
        avoid_patterns=["重复 query"],
        notes="focus on spring style",
    )
    candidate = QueryCandidate(
        query='site:allure.com "capsule wardrobe"',
        result=SearchResult(
            title="Capsule Wardrobe Tips",
            url="https://www.allure.com/story/capsule-wardrobe",
            snippet="A practical guide",
            domain="www.allure.com",
            rank=1,
        ),
    )
    collected = CollectedSource(
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
    current_digest = SourceDigest(
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
    task_result = ResearchTaskResult(
        task_id="iter_1_task_1",
        goal="验证春季 capsule wardrobe 主论点",
        candidate_results=[candidate.result],
        collected_source_refs=["source_1"],
        new_digests=[current_digest],
        raw_findings=["Neutral basics work well."],
        gaps=["来源域名仍偏少"],
        suggested_followups=["capsule wardrobe expert advice"],
    )
    note = CompressedResearchNote(
        task_id="iter_1_task_1",
        summary="本轮拿到了基础 wardrobe 建议。",
        key_findings=["Neutral basics work well."],
        unresolved_gaps=["来源域名仍偏少"],
        recommended_next_queries=["capsule wardrobe expert advice"],
        source_refs=["source_1"],
    )
    state.current_execution = IterationExecution(
        candidate_pool=[candidate],
        task_candidates={"iter_1_task_1": [candidate]},
        task_assessments=[task_result],
        notes=[note],
        collected=[collected],
        digests=[current_digest],
    )
    state.collected_sources = [collected]
    state.digests_by_source = {"source_1": current_digest}
    state.aggregated_notes = [note]
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
    assert payload["iteration_plan"]["objective"] == "形成可发布的小红书长文研究底稿"
    assert payload["iteration_execution"]["task_assessments"][0]["task_id"] == "iter_1_task_1"
    assert payload["iteration_execution"]["notes"][0]["task_id"] == "iter_1_task_1"
    assert payload["aggregated_notes"][0]["task_id"] == "iter_1_task_1"
    assert payload["iteration_execution"]["task_candidates"]["iter_1_task_1"][0]["query"] == 'site:allure.com "capsule wardrobe"'
    assert payload["iteration_execution"]["candidate_count"] == 1
    assert payload["iteration_execution"]["synthesized"] is True
    assert payload["iteration_execution"]["skip_reason"] == ""
    assert payload["iteration_execution"]["new_collected_count"] == 1
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
    assert passed_review.score == 90.0
    assert not failed_review.passed
    assert failed_review.score == 77.5


def test_article_research_review_validator_registers_evidence_tools_when_index_exists(tmp_path) -> None:
    (tmp_path / "source_index.json").write_text("[]", encoding="utf-8")

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            self.tools = kwargs["tools"]

    with (
        patch("src.agents.article_post.research.validator.Agent", FakeAgent),
        patch("src.agents.article_post.research.validator.get_text_model", return_value="model"),
        patch(
            "src.agents.article_post.research.validator.LocalEvidenceStore.get_tools",
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

    agent = ResearchAgent()
    agent.synthesizer.min_source_pages = 2
    agent.synthesizer.min_unique_domains = 2
    agent.synthesizer.rules_validator = FakeRulesValidator()
    agent.synthesizer.review_validator = FakeReviewValidator()
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
    agent = ResearchAgent()
    agent.synthesizer.min_source_pages = 2
    agent.synthesizer.min_unique_domains = 2
    agent.synthesizer.rules_validator = FakeRulesValidator()
    agent.synthesizer.review_validator = FakeReviewValidator()
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

    agent = ResearchAgent()
    agent.synthesizer.min_source_pages = 2
    agent.synthesizer.min_unique_domains = 2
    agent.synthesizer.rules_validator = FakeRulesValidator()
    agent.synthesizer.review_validator = FakeReviewValidator()
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


def test_article_research_latest_snapshot_writes_review_state(tmp_path) -> None:
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
    state.begin_iteration(2)
    state.current_review_result = ArticleResearchReviewResult(
        passed=False,
        score=78.0,
        issues=[issue],
        dimension_results=[dimension_review],
        summary="研究审核未通过",
    )
    state.current_dimension_reviews = [dimension_review]
    latest_file = save_latest_snapshot(state)
    payload = json.loads(Path(latest_file).read_text(encoding="utf-8"))

    assert payload["iteration"] == 2
    assert payload["review_result"]["score"] == 78.0
    assert payload["dimension_reviews"][0]["dimension"] == "downstream_usability"


def test_article_search_candidates_dedupes_results_after_preflight() -> None:
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

    agent = ResearchAgent()
    agent.collector.search_concurrency = 3
    agent.collector.search_client = FakeSearchClient()
    agent.collector._compile_task_queries = lambda task: task.article_queries + task.video_queries

    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.AUTO,
        output_dir=None,
    )
    state.begin_iteration(1)
    tasks = [
        ResearchTask(task_id="task_a", goal="A", article_queries=["q1"]),
        ResearchTask(task_id="task_b", goal="B", article_queries=["q1", "q2"]),
    ]

    task_candidates = asyncio.run(agent._search_candidates(tasks, state))

    assert len(agent.collector.search_client.calls) == 2
    assert agent.collector.search_client.max_active >= 1
    assert agent.collector.search_client.max_active <= agent.collector.search_concurrency
    assert len(state.current_execution.candidate_pool) == 3
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


def test_article_domain_search_client_returns_empty_when_all_backends_fail() -> None:
    with patch.dict("os.environ", {"SERPER_API_KEY": "serper", "TAVILY_API_KEY": "tavily"}):
        client = DomainSearchClient()
        with (
            patch.object(client, "_search_serper", AsyncMock(side_effect=RuntimeError("serper down"))) as serper_mock,
            patch.object(client, "_search_tavily", AsyncMock(side_effect=RuntimeError("tavily down"))) as tavily_mock,
            patch.object(
                client,
                "_search_duckduckgo",
                AsyncMock(side_effect=RuntimeError("duckduckgo blocked")),
            ) as duckduckgo_mock,
        ):
            results = asyncio.run(client.search("capsule wardrobe", max_results=4))

    assert results == []
    serper_mock.assert_awaited_once()
    tavily_mock.assert_awaited_once()
    duckduckgo_mock.assert_awaited_once()


def test_article_domain_search_client_returns_duckduckgo_html_results() -> None:
    expected = [
        SearchResult(
            title="One",
            url="https://www.allure.com/story/one",
            snippet="one",
            domain="www.allure.com",
            rank=1,
        )
    ]

    with patch.dict("os.environ", {"SERPER_API_KEY": "", "TAVILY_API_KEY": ""}):
        client = DomainSearchClient()
        with patch.object(
            client,
            "_search_duckduckgo",
            AsyncMock(return_value=expected),
        ) as duckduckgo_mock:
            results = asyncio.run(client.search("capsule wardrobe", max_results=4))

    assert results == expected
    duckduckgo_mock.assert_awaited_once_with("capsule wardrobe", 4)


def test_article_search_candidates_skips_failed_queries() -> None:
    class PartialFailureSearchClient:
        async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
            if query == "q2":
                raise RuntimeError("blocked")
            return [
                SearchResult(
                    title="One",
                    url="https://www.allure.com/story/one",
                    snippet="one",
                    domain="www.allure.com",
                    rank=1,
                )
            ]

    agent = ResearchAgent()
    agent.collector.search_client = PartialFailureSearchClient()
    agent.collector._compile_task_queries = lambda task: task.article_queries + task.video_queries

    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.AUTO,
        output_dir=None,
    )
    state.begin_iteration(1)
    tasks = [
        ResearchTask(task_id="task_a", goal="A", article_queries=["q1"]),
        ResearchTask(task_id="task_b", goal="B", article_queries=["q2"]),
    ]

    task_candidates = asyncio.run(agent._search_candidates(tasks, state))

    assert [result.url for _, result in task_candidates["task_a"]] == ["https://www.allure.com/story/one"]
    assert task_candidates["task_b"] == []
    assert len(state.current_execution.candidate_pool) == 1
    assert state.seen_candidate_urls == {"https://www.allure.com/story/one"}


def test_article_compile_task_queries_uses_video_domains_for_video_focus() -> None:
    agent = ResearchAgent()
    task = ResearchTask(
        task_id="task_video",
        goal="Find creator interviews about the French girl style myth",
        source_focus="video",
        article_queries=["French girl style myth media analysis"],
        video_queries=["French girl style interview"],
    )

    queries = agent._compile_task_queries(task)

    assert queries[0] == 'site:youtube.com "French girl style interview"'
    assert 'site:allure.com "French girl style myth media analysis"' in queries
    assert "French girl style interview" in queries


def test_article_visit_and_collect_sources_reads_pages_concurrently() -> None:
    class FakePageReader:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def read_page(self, url: str) -> ReadPageResult:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return ReadPageResult(
                ok=True,
                url=url,
                final_url=url,
                title="Capsule wardrobe source",
                author="Jane Doe",
                published_at="2026-03-15",
                text="x" * 1600,
                headings=["Capsule wardrobe guide"],
                paragraphs=["Paragraph"],
            )

    class FakeVideoTranscriber:
        async def transcribe(self, url: str) -> None:
            raise AssertionError("video transcription should not be called")

    agent = ResearchAgent()
    agent.collector.page_visit_concurrency = 3
    agent.collector.page_reader = FakePageReader()
    agent.collector.video_transcriber = FakeVideoTranscriber()
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    state.begin_iteration(1)
    task = ResearchTask(
        task_id="task_1",
        goal="Collect capsule wardrobe article sources",
        source_focus="article",
    )
    candidates = [
        (
            f"q{i}",
                SearchResult(
                    title=f"Capsule wardrobe guide {i}",
                    url=f"https://www.allure.com/story/{i}",
                    snippet=f"Capsule wardrobe snippet {i}",
                    domain="www.allure.com",
                    rank=i,
                ),
            )
        for i in range(1, 5)
    ]

    collected = asyncio.run(agent._visit_and_collect_sources(task, candidates, state))

    assert len(collected) == 3
    assert agent.collector.page_reader.max_active >= 2
    assert agent.collector.page_reader.max_active <= agent.collector.page_visit_concurrency


def test_article_visit_and_collect_sources_uses_video_result_url_when_page_has_no_embed() -> None:
    class FakePageReader:
        async def read_page(self, url: str) -> ReadPageResult:
            return ReadPageResult(
                ok=True,
                url=url,
                final_url=url,
                title="Video Source",
                author="Creator",
                published_at="2026-03-15",
                text="x" * 1600,
                headings=["Heading"],
                paragraphs=["Paragraph"],
                video_urls=[],
                iframe_urls=[],
            )

    class FakeVideoTranscriber:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def transcribe(self, url: str) -> TranscriptResult:
            self.calls.append(url)
            return TranscriptResult(error_message="no transcript")

    agent = ResearchAgent()
    agent.collector.page_visit_concurrency = 2
    agent.collector.page_reader = FakePageReader()
    agent.collector.video_transcriber = FakeVideoTranscriber()
    state = ResearchState(
        topic="French girl style myth",
        target_audience="fashion readers",
        strategy=ArticleStrategy.REPURPOSE_VIDEO,
        output_dir=None,
    )
    state.begin_iteration(1)
    task = ResearchTask(
        task_id="task_video",
        goal="Collect video evidence",
        source_focus="video",
        video_queries=["French girl style interview"],
    )
    candidates = [
        (
            "video_query",
            SearchResult(
                title="Interview",
                url="https://www.youtube.com/watch?v=abc123",
                snippet="Video snippet",
                domain="www.youtube.com",
                rank=1,
            ),
        )
    ]

    collected = asyncio.run(agent._visit_and_collect_sources(task, candidates, state))

    assert collected == []
    assert agent.collector.video_transcriber.calls == ["https://www.youtube.com/watch?v=abc123"]


def test_article_researcher_prioritizes_topical_candidates_before_collection() -> None:
    agent = ResearchAgent()

    async def fake_collect(task, candidates, state, execution):
        return [], [], []

    async def fake_build_digests(state, collected):
        return []

    agent.collector.collect_task_sources = fake_collect
    agent.collector.build_task_digests = fake_build_digests

    state = ResearchState(
        topic="法式穿搭神话的工业起源",
        target_audience="对时尚产业感兴趣的读者",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    state.begin_iteration(1)
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


def test_article_curate_task_sources_prefers_domain_diversity() -> None:
    agent = ResearchAgent()
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    state.begin_iteration(1)
    task = ResearchTask(
        task_id="task_article",
        goal="Compare capsule wardrobe guides across publishers",
        source_focus="article",
        article_queries=["capsule wardrobe guide editors"],
    )
    raw_candidates = [
        CollectedSourceCandidate(
            url="https://www.allure.com/story/guide-a",
            domain="www.allure.com",
            title="Capsule wardrobe guide from Allure",
            author="A",
            published_at="2026-03-10",
            snippet="Editors explain the capsule wardrobe guide.",
            text="x" * 1600,
            headings=["Capsule wardrobe guide"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=92.0,
        ),
        CollectedSourceCandidate(
            url="https://www.allure.com/story/guide-b",
            domain="www.allure.com",
            title="Another capsule wardrobe guide",
            author="B",
            published_at="2026-03-09",
            snippet="Another capsule wardrobe guide.",
            text="x" * 1600,
            headings=["Wardrobe basics"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=88.0,
        ),
        CollectedSourceCandidate(
            url="https://www.elle.com/fashion/capsule-guide",
            domain="www.elle.com",
            title="Editors map a capsule wardrobe",
            author="C",
            published_at="2026-03-08",
            snippet="Capsule wardrobe planning from Elle.",
            text="x" * 1600,
            headings=["Capsule wardrobe"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=89.0,
        ),
        CollectedSourceCandidate(
            url="https://www.vogue.com/article/capsule-wardrobe",
            domain="www.vogue.com",
            title="Vogue capsule wardrobe edit",
            author="D",
            published_at="2026-03-07",
            snippet="Capsule wardrobe edit.",
            text="x" * 1600,
            headings=["Edit"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=86.0,
        ),
        CollectedSourceCandidate(
            url="https://www.byrdie.com/weak-source",
            domain="www.byrdie.com",
            title="Weak source",
            author="",
            published_at="",
            snippet="Weak source",
            text="x" * 1600,
            headings=["Weak"],
            source_type=ArticleSourceType.ARTICLE.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=68.0,
        ),
    ]

    curated, curation_notes = agent._curate_task_sources(task, raw_candidates, state)
    finalized = agent._finalize_curated_sources(state, curated)

    assert [source.domain for source in curated] == [
        "www.allure.com",
        "www.elle.com",
        "www.vogue.com",
    ]
    assert [source.ref for source in finalized] == ["source_1", "source_2", "source_3"]
    assert any(note.startswith("duplicate_domain:") for note in curation_notes)
    assert any(note.startswith("low_quality:") for note in curation_notes)


def test_article_curate_task_sources_prefers_transcript_backed_video() -> None:
    agent = ResearchAgent()
    state = ResearchState(
        topic="French girl style myth",
        target_audience="fashion readers",
        strategy=ArticleStrategy.REPURPOSE_VIDEO,
        output_dir=None,
    )
    state.begin_iteration(1)
    task = ResearchTask(
        task_id="task_video",
        goal="Collect video evidence about the French girl style myth",
        source_focus="video",
        video_queries=["French girl style myth interview"],
    )
    raw_candidates = [
        CollectedSourceCandidate(
            url="https://www.youtube.com/watch?v=aaa",
            domain="www.youtube.com",
            title="French girl style myth interview",
            author="Creator A",
            published_at="2026-03-10",
            snippet="Interview about the French girl style myth.",
            text="x" * 1600,
            headings=["Interview"],
            source_type=ArticleSourceType.VIDEO.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=84.0,
            transcript="Transcript available",
        ),
        CollectedSourceCandidate(
            url="https://www.youtube.com/watch?v=bbb",
            domain="www.youtube.com",
            title="French girl style myth vlog",
            author="Creator B",
            published_at="2026-03-09",
            snippet="Vlog about the French girl style myth.",
            text="x" * 1600,
            headings=["Vlog"],
            source_type=ArticleSourceType.VIDEO.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=87.0,
            transcript="",
        ),
        CollectedSourceCandidate(
            url="https://vimeo.com/123456",
            domain="vimeo.com",
            title="French girl style myth case study",
            author="Creator C",
            published_at="2026-03-08",
            snippet="Case study interview.",
            text="x" * 1600,
            headings=["Case study"],
            source_type=ArticleSourceType.VIDEO.value,
            engagement_hint="",
            paywall_status="public",
            quality_score=83.0,
            transcript="Transcript available",
        ),
    ]

    curated, curation_notes = agent._curate_task_sources(task, raw_candidates, state)

    assert [source.url for source in curated] == [
        "https://www.youtube.com/watch?v=aaa",
        "https://vimeo.com/123456",
    ]
    assert any(note.startswith("video_without_transcript:") for note in curation_notes)


def test_article_researcher_reports_when_all_raw_sources_are_filtered() -> None:
    agent = ResearchAgent()

    async def fake_collect(task, candidates, state, execution):
        return [
            CollectedSourceCandidate(
                url="https://example.com/weak",
                domain="example.com",
                title="Weak",
                author="",
                published_at="",
                snippet="Weak",
                text="x" * 1600,
                headings=["Weak"],
                source_type=ArticleSourceType.ARTICLE.value,
                engagement_hint="",
                paywall_status="public",
                quality_score=68.0,
            )
        ], [], ["low_quality: https://example.com/weak"]

    async def fake_build_digests(state, collected):
        return []

    agent.collector.collect_task_sources = fake_collect
    agent.collector.build_task_digests = fake_build_digests

    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    state.begin_iteration(1)
    task = ResearchTask(
        task_id="task_filter",
        goal="Find strong sources about capsule wardrobe myths",
        source_focus="article",
        article_queries=["capsule wardrobe myth"],
    )

    task_result = asyncio.run(agent.run_researcher_unit(state=state, task=task, candidates=[]))
    note = asyncio.run(agent.compress_task_result(task, task_result))

    assert task_result.raw_source_count == 1
    assert task_result.curated_source_count == 0
    assert task_result.curation_notes == ["low_quality: https://example.com/weak"]
    assert "找到候选来源但未通过质量筛选" in task_result.gaps
    assert note.summary == "Find strong sources about capsule wardrobe myths 找到 1 个候选，但经筛选后未保留可用来源"


def test_article_compress_task_result_uses_fallback_for_low_signal_single_source() -> None:
    class FakeNoteCompressor:
        async def run(self, prompt: str):
            raise AssertionError("note compressor should not run for low-signal single-source tasks")

    agent = ResearchAgent()
    agent.collector.note_compressor = FakeNoteCompressor()
    task = ResearchTask(
        task_id="task_single",
        goal="Summarize a single source",
        source_focus="article",
        article_queries=["single source"],
    )
    task_result = ResearchTaskResult(
        task_id="task_single",
        goal="Summarize a single source",
        raw_source_count=1,
        curated_source_count=1,
        collected_source_refs=["source_1"],
        new_digests=[
            SourceDigest(
                source_ref="source_1",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.allure.com/story/source-one",
                domain="www.allure.com",
                title="Single Source",
                author="Jane Doe",
                published_at="2026-03-15",
                quality_score=88.0,
                chunk_count=1,
                summary="Single-source finding",
                key_points=["A single source can still offer one usable claim."],
            )
        ],
        raw_findings=["Single-source finding"],
        gaps=["来源域名仍偏少"],
        suggested_followups=["single source second opinion"],
    )

    note = asyncio.run(agent.compress_task_result(task, task_result))

    assert note.summary == "Single-source finding"
    assert note.key_findings == ["Single-source finding"]
    assert note.recommended_next_queries == ["single source second opinion"]
    assert note.source_refs == ["source_1"]


def test_article_forward_skips_validate_on_low_signal_iteration() -> None:
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=None,
    )
    state.current_result = _build_valid_article_research_result()
    calls: list[tuple[str, object]] = []

    async def fake_step(current_state, iteration):
        calls.append(("step", iteration))
        current_state.begin_iteration(iteration + 1)
        current_state.current_execution.synthesized = iteration != 0
        current_state.current_execution.skip_reason = (
            "本轮仅新增 1 个来源、1 个 digest，保留到下一轮合并"
            if iteration == 0
            else ""
        )
        current_state.current_result = _build_valid_article_research_result()

    async def fake_validate(output):
        calls.append(("validate", output.summary))
        return ValidationResult.success("ok")

    agent = ResearchAgent()
    agent.MAX_ITERATIONS = 3
    agent.create_state = lambda topic, target_audience, strategy, output_dir=None: state
    agent.step = fake_step
    agent.validate = fake_validate
    agent.finalize = lambda current_state, iteration: calls.append(("finalize", iteration))

    result = asyncio.run(
        agent.forward(
            topic="capsule wardrobe",
            target_audience="25-35岁女性",
            strategy=ArticleStrategy.SYNTHESIZE,
        )
    )

    assert result.summary == "Spring wardrobe research is structured and ready for writing."
    assert calls == [
        ("step", 0),
        ("step", 1),
        ("validate", "Spring wardrobe research is structured and ready for writing."),
        ("finalize", 2),
    ]


def test_article_synthesize_result_passes_current_date_to_prompt(tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeSynthesizer:
        async def run(self, prompt: str):
            return type(
                "RunResult",
                (),
                {
                    "output": ArticleResearchResult(
                        summary="summary",
                        suggested_strategy=ArticleStrategy.SYNTHESIZE,
                    )
                },
            )()

    async def fake_build_local_evidence(*, state, evidence_store):
        return [], str(tmp_path / "digests.json"), str(tmp_path / "source_index.json")

    def fake_prompt(**variables: object) -> str:
        captured.update(variables)
        return "prompt"

    agent = ResearchAgent()
    agent.synthesizer._build_local_evidence = fake_build_local_evidence
    agent.synthesizer._create_synthesizer = lambda evidence_store: FakeSynthesizer()
    state = ResearchState(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        output_dir=tmp_path,
    )
    state.begin_iteration(1)
    state.current_iteration_plan = IterationPlan(objective="objective", audience_focus="audience")

    with patch(
        "src.agents.article_post.research.agent.synthesis_user_prompt",
        side_effect=fake_prompt,
    ):
        asyncio.run(agent.synthesize_result(state, LocalEvidenceStore(tmp_path)))

    assert captured["current_date"] == datetime.now().date().isoformat()


def test_article_review_validator_passes_current_date_to_prompt() -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        async def run(self, prompt: str):
            return type(
                "RunResult",
                (),
                {
                    "output": ResearchDimensionReviewResult(
                        dimension=ResearchReviewDimension.TRACEABILITY,
                        passed=True,
                        score=100.0,
                        issues=[],
                        summary="",
                    )
                },
            )()

    def fake_prompt(**variables: object) -> str:
        captured.update(variables)
        return "review"

    validator = ResearchReviewValidator()
    validator._build_reviewers = lambda output_dir=None: [
        (ResearchReviewDimension.TRACEABILITY, FakeAgent())
    ]

    with patch(
        "src.agents.article_post.research.validator.research_review_user_prompt",
        side_effect=fake_prompt,
    ):
        result = asyncio.run(
            validator.validate(
                _build_valid_article_research_result(),
                context={
                    "topic": "capsule wardrobe",
                    "target_audience": "25-35岁女性",
                    "requested_strategy": ArticleStrategy.SYNTHESIZE,
                    "output_dir": None,
                },
            )
        )

    assert result.passed is True
    assert captured["current_date"] == datetime.now().date().isoformat()


def test_article_content_history_keeps_last_complete_runs() -> None:
    state = ContentState(
        research=_build_valid_article_research_result(),
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        generate_images=True,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[ToolCallPart(tool_name="list_sources", args={}, tool_call_id="call_1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="list_sources", content="[]", tool_call_id="call_1")]),
        ModelResponse(parts=[TextPart(content="初稿结果")]),
        ModelRequest(parts=[UserPromptPart(content="请根据反馈修订")]),
        ModelResponse(parts=[ToolCallPart(tool_name="read_excerpt", args={}, tool_call_id="call_2")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="read_excerpt", content="片段", tool_call_id="call_2")]),
        ModelResponse(parts=[TextPart(content="修订稿")]),
    ]

    filtered = state.get_recent_history(1)

    assert filtered == state.message_history[:4]


def test_article_content_feedback_does_not_mutate_message_history() -> None:
    state = ContentState(
        research=_build_valid_article_research_result(),
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        generate_images=True,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[TextPart(content="初稿结果")]),
    ]

    state.inject_feedback("需要补一个单独的 closing。")

    assert state.last_feedback == "需要补一个单独的 closing。"
    assert len(state.message_history) == 2


def test_article_content_revision_prompt_keeps_research_context() -> None:
    research = _build_valid_article_research_result()

    prompt = content_revision_user_prompt(
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE.value,
        generate_images=True,
        research_json=research.model_dump_json(indent=2),
        feedback="请补一个单独的 closing。",
    )

    assert "研究数据见首轮对话" in prompt
    assert '"source_ref": "source_1"' not in prompt
    assert "请补一个单独的 closing。" in prompt


def test_article_content_step_only_reuses_last_output_message() -> None:
    state = ContentState(
        research=_build_valid_article_research_result(),
        topic="capsule wardrobe",
        target_audience="25-35岁女性",
        strategy=ArticleStrategy.SYNTHESIZE,
        generate_images=True,
    )
    state.message_history = [
        ModelRequest(parts=[UserPromptPart(content="初稿")], instructions="sys"),
        ModelResponse(parts=[ToolCallPart(tool_name="list_sources", args={}, tool_call_id="call_1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="list_sources", content="[]", tool_call_id="call_1")]),
        ModelResponse(parts=[TextPart(content="上一轮完整长文输出")]),
    ]
    state.inject_feedback("请补一个单独的 closing。")

    class FakeRunResult:
        def __init__(self, output: XHSArticleContent) -> None:
            self.output = output

        def new_messages(self) -> list[object]:
            return [
                ModelRequest(parts=[UserPromptPart(content="修订任务")]),
                ModelResponse(parts=[TextPart(content="修订稿")]),
            ]

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def run(self, prompt, message_history=None):
            self.calls.append(
                {
                    "prompt": prompt,
                    "message_history": list(message_history or []),
                }
            )
            return FakeRunResult(
                XHSArticleContent(
                    title="春季胶囊衣橱怎么搭更省心一些",
                    lead="这篇长文会把春季胶囊衣橱的单品、搭配顺序和预算分配拆开讲清楚，方便直接照着执行。",
                    sections=[
                        ArticleSection(
                            heading="先把高频单品定下来",
                            blocks=[
                                ArticleBlock(
                                    block_type=ArticleBlockType.PARAGRAPH,
                                    text="第一步先把白衬衫、针织和轻外套这些高频单品固定下来。",
                                )
                            ],
                        ),
                        ArticleSection(
                            heading="再补通勤场景的变化",
                            blocks=[
                                ArticleBlock(
                                    block_type=ArticleBlockType.PARAGRAPH,
                                    text="柔和剪裁和低饱和配色会让通勤穿搭看起来更松弛，也更容易重复利用。",
                                )
                            ],
                        ),
                    ],
                    closing="按这个顺序整理，衣橱会更稳定，也更容易重复搭配。",
                    hashtags=["春季穿搭", "胶囊衣橱", "通勤穿搭", "衣橱整理"],
                )
            )

    agent = ContentAgent.__new__(ContentAgent)
    agent.generator = FakeGenerator()

    asyncio.run(agent.step(state, 1))

    assert agent.generator.calls[0]["message_history"] == state.message_history[:4]
    assert "请补一个单独的 closing。" in str(agent.generator.calls[0]["prompt"])


def test_article_content_backfills_missing_closing() -> None:
    content = XHSArticleContent(
        strategy=ArticleStrategy.SYNTHESIZE,
        title="法式穿搭神话到底是谁在赚钱",
        lead="这篇长文会把法式穿搭神话的工业起源、平台放大机制和消费后果拆开讲清楚，方便直接理解这套叙事怎么运转。",
        sections=[
            ArticleSection(
                heading="工业叙事先被包装出来",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="品牌和媒体先把一种生活方式包装成可识别的想象，再把它卖给读者。",
                    )
                ],
            ),
            ArticleSection(
                heading="平台负责把想象放大",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="社交平台会不断重复那些最容易传播的气质标签，让它看起来像天然审美。",
                    )
                ],
            ),
            ArticleSection(
                heading="最后变成可售卖的消费选择",
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="当叙事被固定之后，读者更容易把购买当成通往那套形象的捷径。",
                    )
                ],
            ),
        ],
        hashtags=["法式穿搭", "时尚产业", "消费叙事", "审美神话"],
    )

    ContentAgent._ensure_closing(content, "法式穿搭")

    assert content.closing
    assert "法式穿搭" in content.closing


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


def test_article_image_specs_include_richer_prompt_context() -> None:
    research = ArticleResearchResult(
        summary="研究显示春季胶囊衣橱最关键的是基础单品、柔和剪裁和低压力配色。",
        sources=[
            ArticleSource(
                source_ref="source_1",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.allure.com/story/capsule-wardrobe",
                domain="www.allure.com",
                title="Spring Capsule Wardrobe Reset",
                quality_score=90.0,
            ),
            ArticleSource(
                source_ref="source_2",
                source_type=ArticleSourceType.ARTICLE,
                url="https://www.byrdie.com/story/soft-tailoring",
                domain="www.byrdie.com",
                title="Soft Tailoring for Everyday Office Looks",
                quality_score=88.0,
            ),
        ],
        claims=[
            ArticleClaim(
                claim="基础单品先定下来，能显著降低每天搭配的决策疲劳。",
                source_refs=["source_1"],
                section_hint="基础单品先定下来",
            ),
            ArticleClaim(
                claim="柔和剪裁会让通勤装更松弛，也更容易从上班切到下班场景。",
                source_refs=["source_2"],
                section_hint="通勤变化别太用力",
            ),
        ],
        primary_source_ref="source_1",
        suggested_strategy=ArticleStrategy.SYNTHESIZE,
    )
    content = XHSArticleContent(
        strategy=ArticleStrategy.SYNTHESIZE,
        title="春季胶囊衣橱怎么搭更省心",
        lead="这篇长文会把春季最值得留下的基础单品、通勤变化和配色顺序拆开讲清楚，方便直接照着整理。",
        sections=[
            ArticleSection(
                heading="基础单品先定下来",
                summary="先把白衬衫、薄针织和轻外套这些高频单品固定下来。",
                source_refs=["source_1"],
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="第一步先把白衬衫、针织和轻外套这些高频单品固定下来，再去想怎么变化。",
                        source_refs=["source_1"],
                    ),
                    ArticleBlock(
                        block_type=ArticleBlockType.IMAGE_SLOT,
                        image_key="cover",
                        source_refs=["source_1"],
                    ),
                ],
            ),
            ArticleSection(
                heading="通勤变化别太用力",
                summary="柔和剪裁和低饱和配色，会让办公室穿搭更松弛。",
                source_refs=["source_2"],
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.BULLET_LIST,
                        items=[
                            "优先选垂坠感西装和轻薄长裤",
                            "把大面积高饱和色缩到鞋包或小配饰",
                            "通勤和下班都能穿的单品更值得留",
                        ],
                        source_refs=["source_2"],
                    ),
                    ArticleBlock(
                        block_type=ArticleBlockType.IMAGE_SLOT,
                        image_key="section_2",
                        source_refs=["source_2"],
                    ),
                ],
            ),
            ArticleSection(
                heading="最后再补层次和配色",
                summary="顺序对了，衣橱会稳定很多。",
                source_refs=["source_1", "source_2"],
                blocks=[
                    ArticleBlock(
                        block_type=ArticleBlockType.PARAGRAPH,
                        text="最后再决定配色和层次，能避免买回一堆彼此不搭的单品。",
                        source_refs=["source_1", "source_2"],
                    )
                ],
            ),
        ],
        closing="按这个顺序整理，衣橱会更稳，也更容易重复搭配。",
        hashtags=["春季穿搭", "胶囊衣橱", "通勤搭配", "基础单品"],
    )

    specs = ImageAgent._build_specs(content, research)
    specs_by_key = {spec.image_key: spec for spec in specs}

    assert set(specs_by_key) == {"cover", "section_2"}

    cover_spec = specs_by_key["cover"]
    assert cover_spec.image_role == "整篇长文封面图"
    assert cover_spec.text_lines[0] == "春季胶囊衣橱怎么搭更省心"
    assert "第1章：基础单品先定下来" in cover_spec.article_outline
    assert any("基础单品先定下来" in item for item in cover_spec.key_points)

    section_spec = specs_by_key["section_2"]
    assert section_spec.image_role == "章节配图：通勤变化别太用力"
    assert "女性向结构化章节图" in section_spec.visual_direction
    assert any("优先选垂坠感西装和轻薄长裤" in item for item in section_spec.key_points)
    assert any("Soft Tailoring for Everyday Office Looks" in line for line in section_spec.prompt_hint.splitlines())
    assert section_spec.text_lines[0] == "通勤变化别太用力"
    assert any("不要重复整篇文章全部章节" in item for item in section_spec.avoid_points)


def test_article_image_prompts_default_to_female_friendly_aesthetic() -> None:
    system_prompt = image_system_prompt()
    user_prompt = image_user_prompt(
        topic="春季通勤穿搭",
        title="春季胶囊衣橱怎么搭更省心",
        target_audience="25-35岁中文女性用户",
        image_key="cover",
        image_role="整篇长文封面图",
        visual_goal="第一眼说明文章主题和收藏价值，同时保持女性用户更容易喜欢和收藏的专题封面气质",
        visual_direction="女性向杂志感专题封面：一个强主标题，搭配 2-3 个章节标签或信息钩子，柔和配色、有留白，避免做成教材式流程图",
        article_outline="- 第1章：基础单品先定下来",
        key_points="- 基础单品先定下来",
        text_lines="- 春季胶囊衣橱怎么搭更省心",
        avoid_points="- 不要做成冷硬科技海报",
        context_text="导语重点：先把基础单品和通勤变化拆开讲清楚。",
    )

    assert "受众默认是小红书中文女性用户" in system_prompt
    assert "不要做成新闻配图、参数表、理工 dashboard、PPT 模板" in system_prompt
    assert "目标受众: 25-35岁中文女性用户" in user_prompt
    assert "所有图片都必须是女性用户更容易喜欢和收藏的风格" in user_prompt
