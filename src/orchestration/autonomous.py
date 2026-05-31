from __future__ import annotations

from .conversation import ConversationRequest
from .request_parser import is_autonomous_request_text


GENERIC_AUTONOMOUS_TOPICS = {
    "内容",
    "一个内容",
    "一条内容",
    "飞书内容探索",
}


def resolve_autonomous_request(request: ConversationRequest) -> ConversationRequest:
    """Turn open-ended user intent into a concrete researchable brief."""
    if not is_autonomous_request_text(request.message):
        return request
    if request.topic not in GENERIC_AUTONOMOUS_TOPICS and not request.topic.endswith("的内容探索"):
        return request

    if request.audience and request.audience != "泛人群":
        topic = f"适合{request.audience}的近期小红书高互动内容趋势"
    else:
        topic = "近期小红书高互动生活方式内容趋势"

    exploration_note = (
        "系统自主探索要求：先围绕近期小红书高互动内容趋势进行调研，"
        "再选择最适合飞书交付的图文主题与表达方式。"
    )
    message = "\n".join(part for part in (request.message, exploration_note) if part.strip())
    return request.model_copy(update={"topic": topic, "message": message})
