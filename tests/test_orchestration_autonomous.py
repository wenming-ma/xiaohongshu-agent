from __future__ import annotations

from src.orchestration.autonomous import resolve_autonomous_request
from src.orchestration.conversation import ConversationRequest


def test_resolve_autonomous_request_builds_researchable_topic_for_generic_request() -> None:
    request = ConversationRequest(
        topic="飞书内容探索",
        audience="泛人群",
        message="不指定任务，让你自行探索，最后把作品发到飞书。",
    )

    resolved = resolve_autonomous_request(request)

    assert resolved.topic == "近期小红书高互动生活方式内容趋势"
    assert "自主探索要求" in resolved.message


def test_resolve_autonomous_request_uses_specific_audience_when_available() -> None:
    request = ConversationRequest(
        topic="适合通勤女性的内容探索",
        audience="通勤女性",
        message="你自己探索一个适合通勤女性的内容，最后发到飞书。",
    )

    resolved = resolve_autonomous_request(request)

    assert resolved.topic == "适合通勤女性的近期小红书高互动内容趋势"

