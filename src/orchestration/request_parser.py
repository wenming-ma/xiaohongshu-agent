from __future__ import annotations

import re

from .conversation import ContentRoute, ConversationRequest


_KEY_VALUE_PATTERN = re.compile(r"(主题|受众|路线|风格|数量|图片数)\s*[:=：]\s*([^；;\n]+)")

_CHINESE_NUMBERS = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_AUTONOMOUS_TOKENS = (
    "你自己探索",
    "自行探索",
    "自主探索",
    "自己探索",
    "自由探索",
    "你自己决定今天适合发什么内容",
    "自己决定今天适合发什么内容",
    "你自己决定发什么",
    "自己决定发什么",
    "你决定发什么",
    "你看着办",
    "自己看着办",
    "不指定任务",
    "不要指定任务",
    "不指定主题",
    "不要指定主题",
    "随便发",
)


def is_autonomous_request_text(text: str) -> bool:
    return any(token in text for token in _AUTONOMOUS_TOKENS)


def _strip_command_noise(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^(任务|请求|需求)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"[。.!！]+$", "", cleaned)
    return cleaned.strip()


def _extract_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in _KEY_VALUE_PATTERN.findall(text):
        values[key] = value.strip()
    return values


def _normalize_route(value: str | None) -> ContentRoute | None:
    if not value:
        return None
    lowered = value.strip().lower()
    mapping = {
        "image": ContentRoute.IMAGE_POST,
        "image_post": ContentRoute.IMAGE_POST,
        "图文": ContentRoute.IMAGE_POST,
        "图文帖": ContentRoute.IMAGE_POST,
        "article": ContentRoute.ARTICLE_POST,
        "article_post": ContentRoute.ARTICLE_POST,
        "长文": ContentRoute.ARTICLE_POST,
        "文章": ContentRoute.ARTICLE_POST,
        "video": ContentRoute.VIDEO_POST,
        "video_post": ContentRoute.VIDEO_POST,
        "视频": ContentRoute.VIDEO_POST,
    }
    return mapping.get(lowered)


def _extract_audience(text: str) -> str | None:
    for pattern in (
        r"受众\s*[:=：]\s*([^；;\n]+)",
        r"适合([^，。,；;\n]+?)(?:的内容|的帖子|的选题|的方向|$)",
        r"给([^，。,；;\n]+)看",
        r"面向([^，。,；;\n]+)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _extract_topic(text: str, *, audience: str | None) -> str:
    if is_autonomous_request_text(text):
        if audience and audience != "泛人群":
            return f"适合{audience}的内容探索"
        return "飞书内容探索"

    without_structured = _KEY_VALUE_PATTERN.sub("", text)
    cleaned = _strip_command_noise(without_structured)
    cleaned = re.sub(r"(最后)?发到飞书.*$", "", cleaned)
    cleaned = re.sub(r"(请)?执行.*$", "", cleaned)
    cleaned = re.sub(
        r"(不要让我指定图文还是视频|你自己探索|自行探索|自主探索|自己探索|自由探索|你自己决定|自己决定|你决定|你看着办|自己看着办|不指定任务|不要指定任务|不指定主题|不要指定主题|随便发)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(适合%s的)" % re.escape(audience), "", cleaned) if audience else cleaned
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,；;:")
    if cleaned:
        return cleaned
    if audience:
        return f"适合{audience}的内容"
    return "飞书内容探索"


def _extract_style_constraints(text: str, explicit: str | None) -> list[str]:
    if not explicit:
        return []
    items = []
    for item in re.split(r"[,，、]", explicit):
        cleaned = re.sub(r"[。.!！]+.*$", "", item.strip()).strip()
        if cleaned:
            items.append(cleaned)
    return items


def _extract_image_count(text: str) -> int | None:
    stripped = text.strip()
    if re.fullmatch(r"\d{1,2}", stripped):
        value = int(stripped)
        return value if 1 <= value <= 20 else None
    match = re.search(r"(\d{1,2})\s*(?:张|幅|页|p|P)(?:图|图片)?", text)
    if match:
        value = int(match.group(1))
        return value if 1 <= value <= 20 else None
    if stripped in _CHINESE_NUMBERS:
        return _CHINESE_NUMBERS[stripped]
    match = re.search(r"([一两二三四五六七八九])\s*(?:张|幅|页)(?:图|图片)?", text)
    if match:
        return _CHINESE_NUMBERS.get(match.group(1))
    return None


def parse_conversation_request(text: str) -> ConversationRequest:
    raw = text.strip()
    values = _extract_key_values(raw)
    route_hint = _normalize_route(values.get("路线"))
    audience = values.get("受众") or _extract_audience(raw) or "泛人群"
    topic = values.get("主题") or _extract_topic(raw, audience=audience)
    if (
        (is_autonomous_request_text(raw) or "不要让我指定" in raw)
        and audience != "泛人群"
        and topic in {
        "一个内容",
        "一条内容",
        "内容",
        "飞书内容探索",
        }
    ):
        topic = f"适合{audience}的内容探索"
    styles = _extract_style_constraints(raw, values.get("风格"))
    image_count = _extract_image_count(values.get("数量", "") or values.get("图片数", "") or raw)

    return ConversationRequest(
        topic=topic,
        audience=audience,
        message=raw,
        route_hint=route_hint,
        style_constraints=styles,
        image_count=image_count,
    )
