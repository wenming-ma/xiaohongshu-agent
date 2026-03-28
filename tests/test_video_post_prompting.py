from src.agents.video_post.content.agent import ContentAgent
from src.agents.video_post.research.state import ResearchState
from src.agents.video_post.schemas import (
    EngagementMetrics,
    Platform,
    VideoResearchResult,
    VideoSource,
    XHSVideoContent,
)


def _build_source(url: str, platform: Platform = Platform.YOUTUBE) -> VideoSource:
    return VideoSource(
        url=url,
        platform=platform,
        title="sample",
        description="sample",
        engagement=EngagementMetrics(),
    )


def test_video_content_mechanical_check_penalizes_ai_template_phrases() -> None:
    agent = ContentAgent.__new__(ContentAgent)
    content = XHSVideoContent(
        title="这顿晚饭做法其实没有想象中麻烦",
        body=(
            "首先把食材都准备好，其次把火候压低一点。"
            "值得注意的是，这一步其实最影响最后的口感。"
            "总的来说，顺序对了之后整道菜会稳定很多。"
        ),
        hashtags=["晚餐食谱", "一人食"],
        call_to_action="你们做这类家常菜会先处理哪一步？",
    )

    deductions, issues = agent._mechanical_check(content)

    assert deductions >= 15
    assert any("模板化衔接词过多" in issue for issue in issues)


def test_research_state_records_keywords_and_filters_duplicate_urls() -> None:
    state = ResearchState(
        topic="city walk",
        platforms=[Platform.YOUTUBE, Platform.TIKTOK],
        max_videos=5,
        output_dir=None,
    )
    state.seen_urls.add("https://example.com/already-seen")

    result = VideoResearchResult(
        topic="city walk",
        summary="summary",
        keywords=["city walk vlog", "city walk vlog", "weekend walking tour"],
        sources=[
            _build_source("https://example.com/already-seen"),
            _build_source("https://example.com/fresh-1"),
            _build_source("https://example.com/fresh-1"),
            _build_source("https://example.com/fresh-2", platform=Platform.TIKTOK),
        ],
    )

    state.current_result = result
    state.record_result(result)
    state.inject_feedback("需要更多高质量视频")

    assert [source.url for source in result.sources] == [
        "https://example.com/fresh-1",
        "https://example.com/fresh-2",
    ]
    assert state.all_keywords == ["city walk vlog", "weekend walking tour"]
    assert "Already used English queries" in state.last_feedback
    assert "https://example.com/already-seen" in state.last_feedback
    assert "city walk guide" in state.last_feedback or "city walk tips" in state.last_feedback
