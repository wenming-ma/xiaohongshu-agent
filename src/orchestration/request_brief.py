from __future__ import annotations

from dataclasses import dataclass

from .conversation import ConversationRequest


@dataclass(frozen=True)
class RequestBrief:
    topic: str
    audience: str
    user_message: str
    style_constraints: tuple[str, ...]
    image_count: int | None
    single_item_per_image: bool
    execution_text: str
    requirements_text: str


def _detect_single_item_per_image(request: ConversationRequest) -> bool:
    text = " ".join(
        [
            request.topic,
            request.message,
            *request.style_constraints,
        ]
    ).lower()
    markers = (
        "每张图只展示一套",
        "每张只展示一套",
        "每张图一套",
        "每张只放一件",
        "每张图只放一件",
        "每张只放一个",
        "每张图只放一个",
        "一图一套",
        "一图一件",
        "一图一个",
        "单套展示",
        "单套穿搭",
        "单品展示",
        "one outfit per image",
        "single look",
        "single outfit",
        "single item",
    )
    return any(marker in text for marker in markers)


def build_request_brief(request: ConversationRequest) -> RequestBrief:
    style_constraints = tuple(request.style_constraints)
    single_item_per_image = _detect_single_item_per_image(request)
    execution_parts = [f"主题：{request.topic}", f"受众：{request.audience}"]
    requirement_parts: list[str] = []

    if request.image_count is not None:
        image_count_text = f"图片数量：{request.image_count} 张"
        execution_parts.append(image_count_text)
        requirement_parts.append(image_count_text)
    if style_constraints:
        style_text = f"风格约束：{'、'.join(style_constraints)}"
        execution_parts.append(style_text)
        requirement_parts.append(style_text)
    if single_item_per_image:
        single_item_text = "单图单内容：每张图只展示一个主体/一套穿搭"
        execution_parts.append(single_item_text)
        requirement_parts.append(single_item_text)
    if request.message:
        message_text = f"用户原始要求：{request.message}"
        execution_parts.append(message_text)
        requirement_parts.append(message_text)

    return RequestBrief(
        topic=request.topic,
        audience=request.audience,
        user_message=request.message,
        style_constraints=style_constraints,
        image_count=request.image_count,
        single_item_per_image=single_item_per_image,
        execution_text="\n".join(execution_parts),
        requirements_text="需求：" + ("；".join(requirement_parts) if requirement_parts else "未额外指定"),
    )
