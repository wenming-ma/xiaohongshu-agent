from __future__ import annotations

from pathlib import Path
from typing import Any

from .conversation import ConversationRequest
from .feishu_translation import parse_control_action_text
from .request_parser import parse_conversation_request


class ConversationInputTranslator:
    """Translate external session input into ConversationRequest updates."""

    def control_action(self, text: str) -> str:
        return parse_control_action_text(text)

    def control_action_from_event(self, event: Any) -> str:
        if getattr(event, "kind", "") == "control":
            action = getattr(event, "action", "") or self.control_action(getattr(event, "text", ""))
            return action if action == "new_session" else ""
        return self.control_action(getattr(event, "text", ""))

    def apply_event(self, request: ConversationRequest, event: Any) -> ConversationRequest:
        return self.apply(
            request,
            image_path=getattr(event, "image_path", None),
            text=getattr(event, "text", "") or "",
        )

    def apply(
        self,
        request: ConversationRequest,
        *,
        image_path: Path | None = None,
        text: str = "",
    ) -> ConversationRequest:
        messages = [request.message]
        reference_images = list(request.reference_images)

        if image_path is not None:
            reference_images.append(str(image_path))
            messages.append(f"[用户补充参考图]\npath: {image_path}")
        if text.strip():
            messages.append(text.strip())

        followup = parse_conversation_request(text) if text.strip() else None
        style_constraints = list(request.style_constraints)
        if followup is not None:
            style_constraints = list(dict.fromkeys([*style_constraints, *followup.style_constraints]))

        updates: dict[str, object] = {
            "message": "\n".join(part for part in messages if part.strip()),
            "reference_images": reference_images,
            "style_constraints": style_constraints,
        }
        if followup is not None:
            if followup.route_hint is not None:
                updates["route_hint"] = followup.route_hint
            if followup.image_count is not None:
                updates["image_count"] = followup.image_count
            if followup.audience != "泛人群":
                updates["audience"] = followup.audience
            if _should_replace_topic(text, followup.topic):
                updates["topic"] = followup.topic
        return request.model_copy(update=updates)


def _should_replace_topic(text: str, topic: str) -> bool:
    if topic in {"", "飞书内容探索", "内容", "一个内容", "一条内容"}:
        return False
    markers = (
        "换成",
        "换为",
        "改成",
        "改为",
        "改做",
        "重新做",
        "主题=",
        "主题:",
        "主题：",
    )
    return any(marker in text for marker in markers)
