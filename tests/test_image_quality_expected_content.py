from pathlib import Path

import pytest
from PIL import Image

from src.agents.image_post.image.validator import ImageQualityValidator
from src.agents.image_post.schemas import ImageQualityReview, ResearchItem, ResearchResult, XHSContent
from src.orchestration.style_context import ReferenceImageRef


def _write_test_image(path: Path, *, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (16, 16), color=color).save(path)


def test_image_quality_expected_content_uses_research_items_for_detail_groups() -> None:
    content = XHSContent(
        title="西安周末美食路线这样安排",
        body="这是一段用于测试的正文内容。" * 10,
        hashtags=["#西安美食"],
    )
    research = ResearchResult(
        summary="summary",
        items=[
            ResearchItem(title="肉夹馍", content="适合放在早餐路线里，热乎、顶饱"),
            ResearchItem(title="冰峰", content="适合搭配小吃，画面可以出现橙色汽水"),
        ],
        keywords=[],
        sources=[],
    )

    expected = ImageQualityValidator._build_expected_content(
        {
            "content": content,
            "research": research,
            "image_type_info": {
                "type": "detail_1",
                "desc": "详情图1 - 语义分组：早餐路线",
                "group_title": "早餐路线",
                "indices": [0],
            },
        }
    )

    assert "主题板块：早餐路线" in expected
    assert "肉夹馍" in expected
    assert "适合放在早餐路线里" in expected
    assert "冰峰" not in expected
    assert "本图参考信息" in expected
    assert "本图必须覆盖" not in expected


class _RecordingVisionClient:
    def __init__(self) -> None:
        self.single_calls: list[dict] = []
        self.multi_calls: list[dict] = []

    async def analyze_image_bytes_structured(self, **kwargs):
        self.single_calls.append(kwargs)
        return ImageQualityReview(
            passed=True,
            text_clarity_score=90,
            style_score=90,
            aspect_ratio_correct=True,
            text_is_chinese=True,
            issues=[],
            summary="single",
        )

    async def analyze_images_structured(self, **kwargs):
        self.multi_calls.append(kwargs)
        return ImageQualityReview(
            passed=True,
            text_clarity_score=95,
            style_score=95,
            aspect_ratio_correct=True,
            text_is_chinese=True,
            issues=[],
            summary="multi",
        )


@pytest.mark.anyio
async def test_image_quality_validator_compares_generated_image_against_reference_images(tmp_path: Path) -> None:
    generated = tmp_path / "generated.jpg"
    _write_test_image(generated, color=(240, 240, 240))
    reference = tmp_path / "reference.jpg"
    _write_test_image(reference, color=(20, 40, 60))

    validator = ImageQualityValidator()
    recorder = _RecordingVisionClient()
    validator._agent = recorder

    review = await validator.validate(
        generated,
        {
            "topic": "通勤穿搭",
            "image_type": "detail_1",
            "reference_images": [
                ReferenceImageRef(label="reference_1", path=str(reference), mime_type="image/jpeg")
            ],
        },
    )

    assert review.summary == "multi"
    assert recorder.single_calls == []
    assert recorder.multi_calls
    assert recorder.multi_calls[0]["images"] == [
        ("generated_image", generated),
        ("reference_1", reference),
    ]
    assert "必须包含参考图片中的核心衣物" in recorder.multi_calls[0]["prompt"]
