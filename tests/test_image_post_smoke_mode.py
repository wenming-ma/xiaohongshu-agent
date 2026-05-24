import argparse
import asyncio
import importlib.util
from pathlib import Path

from src.agents.image_post.image.agent import ImageAgent
from src.agents.image_post.schemas import ResearchItem, ResearchResult, XHSImagePostOutput
from src.config.settings import ImageConfig, ResearchConfig, RetryConfig, ReviewConfig


def _load_workshop_module():
    script_path = Path("workshop/image_post/run.py").resolve()
    spec = importlib.util.spec_from_file_location("image_post_run_for_smoke_mode", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_image_post_workshop_smoke_mode_temporarily_lowers_runtime_config(monkeypatch, tmp_path):
    module = _load_workshop_module()
    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        '[{"topic":"快速验链路","audience":"测试用户"}]',
        encoding="utf-8",
    )

    original_min_posts = ResearchConfig.MIN_POSTS_RESEARCHED
    original_max_detail_images = ImageConfig.MAX_DETAIL_IMAGES
    captured = {}

    class _FastPipeline:
        async def execute(self, input_data):
            captured.update(
                {
                    "min_posts": ResearchConfig.MIN_POSTS_RESEARCHED,
                    "research_retries": ResearchConfig.VALIDATION_MAX_RETRIES,
                    "content_iterations": ReviewConfig.MAX_ITERATIONS,
                    "grouping_retries": ImageConfig.GROUPING_REVIEW_MAX_RETRIES,
                    "min_detail_images": ImageConfig.MIN_DETAIL_IMAGES,
                    "max_detail_images": ImageConfig.MAX_DETAIL_IMAGES,
                    "image_retries": RetryConfig.MAX_RETRIES,
                    "publish": input_data.publish,
                }
            )
            return XHSImagePostOutput(
                success=True,
                title="快速验链路标题",
                hashtags=["#测试"],
                image_count=0,
                output_dir=str(tmp_path),
            )

    monkeypatch.setattr(module, "XHSImagePostPipeline", _FastPipeline)
    monkeypatch.setattr(module, "SCRIPT_DIR", tmp_path)

    args = argparse.Namespace(
        topics_file=topics_file,
        start_index=1,
        limit=1,
        max_retries=1,
        retry_delay=0,
        sleep=None,
        no_feishu=True,
        publish=False,
        feishu_only=True,
        smoke_test=True,
    )

    exit_code = asyncio.run(module.run_batch(args))

    assert exit_code == 0
    assert captured == {
        "min_posts": 1,
        "research_retries": 1,
        "content_iterations": 1,
        "grouping_retries": 1,
        "min_detail_images": 0,
        "max_detail_images": 0,
        "image_retries": 1,
        "publish": False,
    }
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
