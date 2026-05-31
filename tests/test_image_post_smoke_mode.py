import asyncio

from src.agents.image_post.image.agent import ImageAgent
from src.agents.image_post.schemas import ResearchItem, ResearchResult
from src.config.settings import ImageConfig, ResearchConfig, RetryConfig, ReviewConfig
from src.orchestration.smoke import orchestration_smoke_test_overrides


def test_orchestration_smoke_mode_temporarily_lowers_runtime_config():
    original_min_posts = ResearchConfig.MIN_POSTS_RESEARCHED
    original_max_detail_images = ImageConfig.MAX_DETAIL_IMAGES

    with orchestration_smoke_test_overrides(True):
        assert ResearchConfig.MIN_POSTS_RESEARCHED == 1
        assert ResearchConfig.VALIDATION_MAX_RETRIES == 1
        assert ReviewConfig.MAX_ITERATIONS == 1
        assert ImageConfig.GROUPING_REVIEW_MAX_RETRIES == 1
        assert ImageConfig.MIN_DETAIL_IMAGES == 0
        assert ImageConfig.MAX_DETAIL_IMAGES == 0
        assert RetryConfig.MAX_RETRIES == 3

    assert ResearchConfig.MIN_POSTS_RESEARCHED == original_min_posts
    assert ImageConfig.MAX_DETAIL_IMAGES == original_max_detail_images


def test_image_agent_skips_grouping_when_detail_images_are_disabled(monkeypatch):
    monkeypatch.setattr(ImageConfig, "MIN_DETAIL_IMAGES", 0)
    monkeypatch.setattr(ImageConfig, "MAX_DETAIL_IMAGES", 0)

    agent = ImageAgent.__new__(ImageAgent)
    research = ResearchResult(
        summary="summary",
        items=[ResearchItem(title="item", content="content")],
        keywords=[],
        sources=[],
    )

    groups = asyncio.run(agent.compute_groups(research=research, topic="快速验链路"))

    assert groups == []
