from src.agents.image_post.image.validator import ImageQualityValidator
from src.agents.image_post.schemas import ResearchItem, ResearchResult, XHSContent


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
