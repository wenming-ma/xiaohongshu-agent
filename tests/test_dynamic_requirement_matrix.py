from __future__ import annotations

import pytest

from src.orchestration.request_brief import build_request_brief
from src.orchestration.request_parser import parse_conversation_request


@pytest.mark.parametrize(
    ("raw", "expected_count", "expected_single"),
    [
        (
            "做 5 张图，每张图只展示一套登山通勤穿搭，衣服平铺在纯色背景上，不要人物。",
            5,
            True,
        ),
        (
            "做一组面试通勤好物，每张只放一件产品，背景用低饱和纯色，不确定图数你自己决定。",
            None,
            True,
        ),
        (
            "约会场景穿搭灵感，不用固定图片数量，你根据调研结果分组，风格高级感一点。",
            None,
            False,
        ),
        (
            "搜集并生成图片：露营桌搭，6张图，一图一个主体，极简、无人物。",
            6,
            True,
        ),
        (
            "不指定任务，让你自行探索，最后把作品发到飞书。",
            None,
            False,
        ),
    ],
)
def test_free_text_requirement_matrix(raw: str, expected_count: int | None, expected_single: bool) -> None:
    request = parse_conversation_request(raw)
    brief = build_request_brief(request)

    assert request.image_count == expected_count
    assert brief.single_item_per_image is expected_single
    assert request.style_constraints == []


def test_partial_autonomy_about_image_count_does_not_become_global_exploration() -> None:
    request = parse_conversation_request(
        "做一组面试通勤好物，每张只放一件产品，背景用低饱和纯色，不确定图数你自己决定。"
    )

    assert request.topic != "飞书内容探索"
    assert "面试通勤好物" in request.topic
