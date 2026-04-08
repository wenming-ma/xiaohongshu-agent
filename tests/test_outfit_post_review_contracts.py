import asyncio
import json
from pathlib import Path

from src.agents.outfit_post.content.agent import ContentAgent
from src.agents.outfit_post.content.state import ContentState
from src.agents.outfit_post.publish.agent import PublisherAgent
from src.agents.outfit_post.research.validator import (
    ResearchDepthValidator,
    ResearchReviewValidator,
)
from src.agents.outfit_post.schemas import (
    ContentSource,
    ResearchItem,
    ResearchResult,
    ReviewIssue,
    ReviewResult,
    XHSContent,
)
from src.agents.outfit_post.utils.research import merge_results, save_iteration_result


class _FakeRunResult:
    def __init__(self, output):
        self.output = output

    def new_messages(self):
        return []


class _FakeReviewer:
    def __init__(self, output):
        self._output = output

    async def run(self, prompt, message_history=None):
        return _FakeRunResult(self._output)


def _build_research() -> ResearchResult:
    return ResearchResult(
        summary="summary",
        items=[ResearchItem(title="look 1", content="alpha")],
        keywords=[],
        sources=[],
    )


def test_xhscontent_title_schema_limits_to_20_chars() -> None:
    try:
        XHSContent(
            title="123456789012345678901",
            body="这是一段用于测试的正文。" * 10,
            hashtags=["#测试"],
        )
    except Exception:
        return

    raise AssertionError("expected title schema validation to reject 21-char title")


def test_content_validate_rejects_contradictory_reviewer_success() -> None:
    agent = ContentAgent.__new__(ContentAgent)
    agent.reviewer = _FakeReviewer(
        ReviewResult(
            passed=True,
            score=95,
            issues=[
                ReviewIssue(
                    type="logic_error",
                    severity="critical",
                    description="核心逻辑冲突",
                    suggestion="修正",
                )
            ],
            summary="存在 critical 问题",
        )
    )
    agent._current_state = ContentState(research=_build_research(), topic="法式通勤", groups=[])

    result = asyncio.run(
        agent.validate(
            XHSContent(
                title="法式通勤穿搭这样搭更显气质",
                body="这是一段用于测试的正文。" * 10,
                hashtags=["#法式通勤"],
            )
        )
    )

    assert result.passed is False
    assert "critical" in result.feedback.lower()


def test_research_review_validator_rejects_contradictory_reviewer_success() -> None:
    validator = ResearchReviewValidator(min_posts=3)
    validator._reviewer = _FakeReviewer(
        ReviewResult(
            passed=True,
            score=90,
            issues=[
                ReviewIssue(
                    type="missing_field",
                    severity="critical",
                    description="来源缺失",
                    suggestion="补齐 sources",
                )
            ],
            summary="仍有致命问题",
        )
    )

    result = asyncio.run(
        validator.validate(
            _build_research(),
            {"topic": "法式通勤", "target_audience": "年轻女性"},
        )
    )

    assert result.passed is False
    assert "来源缺失" in result.feedback


def test_research_depth_validator_requires_minimum_sources() -> None:
    validator = ResearchDepthValidator(min_posts=3)
    result = asyncio.run(
        validator.validate(
            ResearchResult(
                summary="summary",
                items=[ResearchItem(title="look 1", content="alpha")],
                keywords=[],
                sources=[
                    ContentSource(
                        url="https://www.xiaohongshu.com/explore/1",
                        title="look 1",
                        domain="www.xiaohongshu.com",
                    ),
                    ContentSource(
                        url="https://www.xiaohongshu.com/explore/2",
                        title="look 2",
                        domain="www.xiaohongshu.com",
                    ),
                ],
            ),
            {
                "tracked_post_count": 3,
                "tracked_urls": [
                    "https://www.xiaohongshu.com/explore/1",
                    "https://www.xiaohongshu.com/explore/2",
                    "https://www.xiaohongshu.com/explore/3",
                ],
            },
        )
    )

    assert result.passed is False
    assert "来源数量不足" in result.feedback


def test_research_depth_validator_rejects_inflated_sources() -> None:
    validator = ResearchDepthValidator(min_posts=3)
    result = asyncio.run(
        validator.validate(
            ResearchResult(
                summary="summary",
                items=[ResearchItem(title="look 1", content="alpha")],
                keywords=[],
                sources=[
                    ContentSource(
                        url=f"https://www.xiaohongshu.com/explore/{idx}",
                        title=f"look {idx}",
                        domain="www.xiaohongshu.com",
                    )
                    for idx in range(1, 5)
                ],
            ),
            {
                "tracked_post_count": 2,
                "tracked_urls": [
                    "https://www.xiaohongshu.com/explore/1",
                    "https://www.xiaohongshu.com/explore/2",
                ],
            },
        )
    )

    assert result.passed is False
    assert "数据异常" in result.feedback


def test_merge_results_preserves_item_provenance_and_canonicalizes_source_urls() -> None:
    merged = merge_results(
        [
            ResearchResult(
                summary="round1",
                items=[
                    ResearchItem(
                        title="版型建议",
                        content="白衬衫适合搭直筒裤",
                        item_type="note",
                        source_ref="post_1",
                    )
                ],
                keywords=["通勤"],
                sources=[
                    ContentSource(
                        url="https://www.xiaohongshu.com/explore/abc?utm_source=feed",
                        title="post 1",
                        domain="www.xiaohongshu.com",
                    )
                ],
            ),
            ResearchResult(
                summary="round2",
                items=[
                    ResearchItem(
                        title="版型建议",
                        content="白衬衫适合搭直筒裤",
                        item_type="comment",
                        source_ref="comment_7",
                    )
                ],
                keywords=["法式"],
                sources=[
                    ContentSource(
                        url="https://www.xiaohongshu.com/explore/abc?xsec_token=123",
                        title="post 1 dup",
                        domain="www.xiaohongshu.com",
                    )
                ],
            ),
        ],
        tracked_stats={},
    )

    assert len(merged.items) == 2
    assert len(merged.sources) == 1
    assert merged.sources[0].url == "https://www.xiaohongshu.com/explore/abc"


def test_save_iteration_result_uses_collision_resistant_filename(tmp_path: Path) -> None:
    saved_files: list[str] = []
    result = ResearchResult(
        summary="summary",
        items=[ResearchItem(title="look 1", content="alpha")],
        keywords=[],
        sources=[],
    )

    first = save_iteration_result(result, "法式通勤", 1, {}, tmp_path, saved_files)
    second = save_iteration_result(result, "法式通勤", 1, {}, tmp_path, saved_files)

    assert first != second
    assert Path(first).name.startswith("research_iter1_")
    assert Path(second).name.startswith("research_iter1_")


def test_publish_forward_fails_fast_on_missing_images(tmp_path: Path) -> None:
    agent = PublisherAgent.__new__(PublisherAgent)

    def _unexpected_reinit(output_dir):
        raise AssertionError("publish setup should not start for invalid images")

    async def _unexpected_step(user_prompt: str):
        raise AssertionError("publish step should not run for invalid images")

    agent.init_mcp_server = _unexpected_reinit
    agent.init_tools = lambda: None
    agent.init_agent = lambda: None
    agent.step = _unexpected_step
    agent.validate = lambda output: None

    content = XHSContent(
        title="法式通勤穿搭这样搭更显气质",
        body="这是一段用于测试的正文。" * 10,
        hashtags=["#法式通勤"],
    )

    try:
        asyncio.run(agent.forward(content=content, images=[tmp_path / "missing.png"], output_dir=tmp_path))
    except ValueError as exc:
        assert "不存在" in str(exc)
        return

    raise AssertionError("expected forward to fail fast for missing image path")


def test_save_iteration_result_payload_remains_readable_json(tmp_path: Path) -> None:
    saved_files: list[str] = []
    result = ResearchResult(
        summary="summary",
        items=[ResearchItem(title="look 1", content="alpha")],
        keywords=[],
        sources=[],
    )

    saved = save_iteration_result(result, "法式通勤", 2, {"post_detail_count": 1}, tmp_path, saved_files)
    payload = json.loads(Path(saved).read_text(encoding="utf-8"))

    assert payload["iteration"] == 2
    assert payload["topic"] == "法式通勤"
