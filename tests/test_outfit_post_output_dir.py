import asyncio
from datetime import datetime
from pathlib import Path

from src.agents.outfit_post import OutfitPostInput, OutfitPostPipeline
from src.agents.outfit_post.schemas import (
    GeneratedImage,
    ImageResult,
    OutfitItem,
    ReferenceImageResult,
    ResearchItem,
    ResearchResult,
    XHSContent,
)
from src.config.settings import PathConfig


def test_path_config_defines_dedicated_outfit_project_dir() -> None:
    assert PathConfig.OUTFIT_PROJECT_DIR == PathConfig._PROJECT_ROOT / "posts" / "outfit-posts"


def test_outfit_pipeline_uses_dedicated_output_dir(monkeypatch, tmp_path: Path) -> None:
    image_root = tmp_path / "image-posts"
    outfit_root = tmp_path / "outfit-posts"
    monkeypatch.setattr(PathConfig, "IMAGE_PROJECT_DIR", image_root)
    monkeypatch.setattr(PathConfig, "OUTFIT_PROJECT_DIR", outfit_root, raising=False)

    class _FakeDiscussAgent:
        async def forward(self, output_dir: Path, topic_hint: str):
            return [OutfitItem(name="白色衬衫")], ReferenceImageResult(skipped=True), "休闲穿搭：白色衬衫 穿法搭配"

    class _FakeResearchAgent:
        async def forward(self, topic: str, target_audience: str, output_dir: Path):
            return ResearchResult(
                summary="summary",
                items=[ResearchItem(title="look 1", content="alpha")],
                keywords=[],
                sources=[],
            )

    class _FakeContentAgent:
        async def forward(self, research: ResearchResult, topic: str, groups: list[dict]):
            return XHSContent(
                title="休闲穿搭这样穿更好看",
                body="这是一段用于测试的正文。" * 10,
                hashtags=["#休闲穿搭"],
                call_to_action="",
            )

    class _FakeImageAgent:
        async def compute_groups(self, research: ResearchResult, topic: str, ref_item_names=None):
            return [{"title": topic, "indices": [0], "ref_items": []}]

        async def forward(
            self,
            content: XHSContent,
            research: ResearchResult,
            topic: str,
            output_dir: Path,
            groups: list[dict] | None = None,
            reference_images: ReferenceImageResult | None = None,
        ):
            return ImageResult(
                images=[
                    GeneratedImage(
                        image_path=str(output_dir / "cover.png"),
                        prompt_used="prompt",
                        image_type="cover",
                    )
                ],
                total_count=1,
                generated_at=datetime.now().isoformat(),
            )

    class _FakePublisherAgent:
        async def forward(self, content: XHSContent, images: list[Path], output_dir: Path):
            raise AssertionError("publish should be skipped in this test")

    monkeypatch.setattr("src.agents.outfit_post.discuss.DiscussAgent", _FakeDiscussAgent)
    monkeypatch.setattr("src.agents.outfit_post.research.ResearchAgent", _FakeResearchAgent)
    monkeypatch.setattr("src.agents.outfit_post.content.ContentAgent", _FakeContentAgent)
    monkeypatch.setattr("src.agents.outfit_post.image.ImageAgent", _FakeImageAgent)
    monkeypatch.setattr("src.agents.outfit_post.publish.PublisherAgent", _FakePublisherAgent)

    pipeline = OutfitPostPipeline()
    result = asyncio.run(
        pipeline.execute(
            OutfitPostInput(
                topic="休闲穿搭",
                audience="年轻女性",
                publish=False,
            )
        )
    )

    assert result.success is True
    assert Path(result.output_dir).parent == outfit_root
    assert str(result.output_dir).startswith(str(outfit_root))
    assert not str(result.output_dir).startswith(str(image_root))
