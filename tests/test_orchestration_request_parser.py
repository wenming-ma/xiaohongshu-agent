from __future__ import annotations

from src.orchestration.conversation import ContentRoute
from src.orchestration.request_parser import parse_conversation_request


def test_parse_structured_guided_request() -> None:
    request = parse_conversation_request(
        "任务：主题=纯色背景穿搭；受众=通勤女生；路线=image_post；风格=纯色背景,单套展示。请执行。"
    )

    assert request.topic == "纯色背景穿搭"
    assert request.audience == "通勤女生"
    assert request.route_hint is ContentRoute.IMAGE_POST
    assert request.style_constraints == ["纯色背景", "单套展示"]


def test_parse_image_count_from_free_text() -> None:
    request = parse_conversation_request(
        "我想发一个登山穿搭帖子，大概 5 张图，不要人物，衣服平铺在纯色背景上。"
    )

    assert request.image_count == 5
    assert request.style_constraints == []


def test_parse_free_text_does_not_keyword_extract_style_constraints() -> None:
    request = parse_conversation_request(
        "做 2 张图，每张图只展示一套穿搭，背景必须纯色，不要人物，真实摄影质感。"
    )

    assert request.image_count == 2
    assert request.style_constraints == []


def test_parse_image_count_from_explicit_bare_number_field() -> None:
    request = parse_conversation_request(
        "主题：纯色背景通勤面试穿搭；受众：通勤女性；图片数：3；风格：纯色背景、无人物。"
    )

    assert request.image_count == 3


def test_parse_open_ended_request_without_route_hint() -> None:
    request = parse_conversation_request(
        "你自己探索一个适合通勤女生的内容，最后发到飞书，不要让我指定图文还是视频。"
    )

    assert request.route_hint is None
    assert request.audience == "通勤女生"
    assert "适合通勤女生的内容" in request.topic


def test_parse_unspecified_autonomous_request_as_clean_exploration() -> None:
    request = parse_conversation_request("不指定任务，让你自行探索，最后把作品发到飞书。")

    assert request.route_hint is None
    assert request.audience == "泛人群"
    assert request.topic == "飞书内容探索"


def test_parse_autonomous_decision_request_as_clean_exploration() -> None:
    request = parse_conversation_request("你自己决定今天适合发什么内容，最后发到飞书。")

    assert request.route_hint is None
    assert request.topic == "飞书内容探索"


def test_parse_subscription_request_preserves_intent_in_message() -> None:
    request = parse_conversation_request("订阅主题：通勤穿搭，每周寻找热点并生成一组图片，发到飞书。")

    assert "通勤穿搭" in request.topic
    assert "订阅主题" in request.message
    assert "寻找热点" in request.message


def test_parse_asset_collection_request_preserves_intent_in_message() -> None:
    request = parse_conversation_request("搜集并生成图片：高级感通勤穿搭，风格=纯色背景。")

    assert "搜集并生成图片" in request.message
    assert request.style_constraints == ["纯色背景"]
