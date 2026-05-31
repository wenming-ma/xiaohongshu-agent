from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from src.config.settings import ImageConfig, ResearchConfig, RetryConfig, ReviewConfig


SMOKE_TEST_CONFIG_OVERRIDES: tuple[tuple[type, str, Any], ...] = (
    (ResearchConfig, "MIN_POSTS_RESEARCHED", 1),
    (ResearchConfig, "VALIDATION_MAX_RETRIES", 1),
    (ReviewConfig, "MAX_ITERATIONS", 1),
    (ImageConfig, "GROUPING_REVIEW_MAX_RETRIES", 1),
    (ImageConfig, "MIN_DETAIL_IMAGES", 0),
    (ImageConfig, "MAX_DETAIL_IMAGES", 0),
    (RetryConfig, "MAX_RETRIES", 3),
    (RetryConfig, "AGENT_RETRIES", 1),
)


@contextmanager
def orchestration_smoke_test_overrides(enabled: bool) -> Iterator[None]:
    """Temporarily reduce expensive workflow thresholds for end-to-end smoke runs."""
    if not enabled:
        yield
        return

    originals = [(config_cls, name, getattr(config_cls, name)) for config_cls, name, _ in SMOKE_TEST_CONFIG_OVERRIDES]
    try:
        for config_cls, name, value in SMOKE_TEST_CONFIG_OVERRIDES:
            setattr(config_cls, name, value)
        yield
    finally:
        for config_cls, name, value in originals:
            setattr(config_cls, name, value)
