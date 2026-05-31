from src.config.settings import ImageConfig, ResearchConfig
from src.orchestration.smoke import orchestration_smoke_test_overrides


def test_orchestration_smoke_test_overrides_runtime_thresholds() -> None:
    original_min_posts = ResearchConfig.MIN_POSTS_RESEARCHED
    original_max_images = ImageConfig.MAX_DETAIL_IMAGES

    with orchestration_smoke_test_overrides(enabled=True):
        assert ResearchConfig.MIN_POSTS_RESEARCHED == 1
        assert ImageConfig.MAX_DETAIL_IMAGES == 0

    assert ResearchConfig.MIN_POSTS_RESEARCHED == original_min_posts
    assert ImageConfig.MAX_DETAIL_IMAGES == original_max_images


def test_orchestration_smoke_test_overrides_noop_when_disabled() -> None:
    original_min_posts = ResearchConfig.MIN_POSTS_RESEARCHED

    with orchestration_smoke_test_overrides(enabled=False):
        assert ResearchConfig.MIN_POSTS_RESEARCHED == original_min_posts
