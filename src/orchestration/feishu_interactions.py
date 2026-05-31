from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.utils.feishu_notifier import FeishuNotifier, get_feishu_notifier

from .conversation import ContentRoute, ConversationRequest
from .request_parser import is_autonomous_request_text, parse_conversation_request
from .schemas import DeliveryPackage, ResultEnvelope


RouteResolver = Callable[[ConversationRequest], ContentRoute]


class FeishuInteractionTools:
    """Feishu-facing tools used by the workflow layer for user interaction."""

    def __init__(
        self,
        *,
        notifier: FeishuNotifier | Any | None = None,
        route_resolver: RouteResolver | None = None,
    ) -> None:
        self.notifier = notifier or get_feishu_notifier()
        self.route_resolver = route_resolver

    async def send_busy(self, reason: str) -> None:
        await self.notifier.send_message(f"当前会话忙碌中，暂时无法接管：{reason}")

    async def send_session_unavailable(self) -> None:
        await self.notifier.send_message("无法建立飞书交互会话。")

    async def send_runtime_error(self) -> None:
        await self.notifier.send_message("处理请求时发生异常，请稍后重试。")

    async def clarify_request_if_needed(self, session: object, request: ConversationRequest) -> ConversationRequest:
        if self._needs_route_choice(request):
            request = await self.ask_route_choice(session, request)

        route = request.route_hint or self._resolve_route(request)
        if route is ContentRoute.IMAGE_POST and self._needs_style_choices(request):
            request = await self.ask_style_choices(session, request)
        return request

    async def announce_execution_started(
        self,
        session: object,
        request: ConversationRequest,
        *,
        route_label: str,
    ) -> None:
        await self.notifier.send_session_message(
            session,
            (
                "已收到请求，开始执行。\n"
                f"主题：{request.topic}\n"
                f"受众：{request.audience}\n"
                f"路线：{route_label}"
            ),
            phase="planning",
            summary=request.topic,
        )

    async def announce_delivery_result(
        self,
        session: object,
        result: ResultEnvelope[DeliveryPackage],
    ) -> None:
        if result.payload is not None:
            await self.notifier.send_session_message(
                session,
                f"已完成 {result.payload.route} 交付，标题：{result.payload.title}",
                phase="completed",
                summary=result.payload.summary,
            )
            return
        await self.notifier.send_session_message(
            session,
            f"执行失败：{result.error_message or result.summary}",
            phase="failed",
            summary=result.summary,
        )

    async def ask_route_choice(self, session: object, request: ConversationRequest) -> ConversationRequest:
        await self.notifier.send_session_card_message(
            session,
            (
                "我先按你的话理解任务，不需要固定格式。\n\n"
                f"当前主题：{request.topic}\n"
                f"当前受众：{request.audience}\n\n"
                "这次更适合做成哪种交付？如果不想选，点“你决定”。"
            ),
            [
                ("图文", "__route__:image_post"),
                ("文章", "__route__:article_post"),
                ("视频", "__route__:video_post"),
                ("你决定，直接开始", "__route__:auto"),
            ],
            phase="clarify_route",
            summary=request.topic,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(
            session,
            phase="clarify_route",
            summary=request.topic,
        )
        return self._apply_route_reply(request, reply)

    async def ask_style_choices(self, session: object, request: ConversationRequest) -> ConversationRequest:
        if not hasattr(self.notifier, "send_session_form_card"):
            return request
        await self.notifier.send_session_form_card(
            session,
            (
                "图片风格可以点选，也可以不选直接确认。\n\n"
                "我会把你选的风格作为约束交给后续 Agent。"
            ),
            [
                {"name": "style_pure_color", "text": "纯色背景", "checked": False},
                {"name": "style_single_look", "text": "每张图只展示一套穿搭", "checked": False},
                {"name": "style_minimal", "text": "极简干净", "checked": False},
                {"name": "style_low_saturation", "text": "低饱和高级感", "checked": False},
            ],
            phase="clarify_style",
            input_name="style_extra",
            input_placeholder="也可以补充一句风格要求",
            submit_label="确认这些要求",
            summary=request.topic,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(
            session,
            phase="clarify_style",
            summary=request.topic,
        )
        return self._apply_style_reply(request, reply)

    def _needs_route_choice(self, request: ConversationRequest) -> bool:
        if request.route_hint is not None:
            return False
        text = " ".join([request.topic, request.message]).lower()
        if is_autonomous_request_text(request.message):
            return False
        if any(token in text for token in ("图片", "图文", "image", "文章", "长文", "article", "视频", "video")):
            return False
        generic_topics = {"内容", "一个内容", "一条内容", "飞书内容探索"}
        return request.topic in generic_topics or len(request.message.strip()) <= 14 or any(
            token in text for token in ("不知道", "不确定", "随便", "帮我想", "你看着办")
        )

    def _needs_style_choices(self, request: ConversationRequest) -> bool:
        if request.style_constraints:
            return False
        if is_autonomous_request_text(request.message):
            return False
        text = " ".join([request.topic, request.message])
        if any(token in text for token in ("风格", "纯色", "单套", "低饱和", "高级感", "极简", "干净")):
            return False
        return len(request.message.strip()) <= 40 or any(token in text for token in ("图片", "图文", "穿搭"))

    def _resolve_route(self, request: ConversationRequest) -> ContentRoute:
        if self.route_resolver is not None:
            return self.route_resolver(request)
        return self._infer_route_for_clarification(request)

    def _infer_route_for_clarification(self, request: ConversationRequest) -> ContentRoute:
        text = " ".join([request.topic, request.message]).lower()
        if any(token in text for token in ("视频", "video", "短片", "混剪", "reel", "clip")):
            return ContentRoute.VIDEO_POST
        if any(token in text for token in ("长文", "文章", "article", "深度", "解读")):
            return ContentRoute.ARTICLE_POST
        return ContentRoute.IMAGE_POST

    def _apply_route_reply(self, request: ConversationRequest, reply: str) -> ConversationRequest:
        text = reply.strip()
        if text == "__route__:auto":
            return request
        if text.startswith("__route__:"):
            route_value = text.split(":", 1)[1]
            try:
                return request.model_copy(update={"route_hint": ContentRoute(route_value)})
            except ValueError:
                return request

        followup = parse_conversation_request(text)
        return self._merge_request(request, followup)

    def _apply_style_reply(self, request: ConversationRequest, reply: str) -> ConversationRequest:
        text = reply.strip()
        if text.startswith("__FORM__:"):
            try:
                values = json.loads(text.removeprefix("__FORM__:"))
            except json.JSONDecodeError:
                return request
            selected = self._style_values_from_form(values)
            if not selected:
                return request
            return request.model_copy(update={"style_constraints": selected})

        followup = parse_conversation_request(text)
        return self._merge_request(request, followup)

    def _style_values_from_form(self, values: dict[str, Any]) -> list[str]:
        labels = {
            "style_pure_color": "纯色背景",
            "style_single_look": "每张图只展示一套穿搭",
            "style_minimal": "极简干净",
            "style_low_saturation": "低饱和高级感",
        }
        selected: list[str] = []
        for key, label in labels.items():
            value = values.get(key)
            if value is True or value == "true" or value == label:
                selected.append(label)
        extra = values.get("style_extra")
        if isinstance(extra, str) and extra.strip():
            selected.append(extra.strip())
        return selected

    def _merge_request(self, base: ConversationRequest, followup: ConversationRequest) -> ConversationRequest:
        styles = list(dict.fromkeys([*base.style_constraints, *followup.style_constraints]))
        updates: dict[str, Any] = {
            "message": "\n".join(part for part in (base.message, followup.message) if part.strip()),
            "style_constraints": styles,
        }
        if followup.route_hint is not None:
            updates["route_hint"] = followup.route_hint
        if followup.image_count is not None:
            updates["image_count"] = followup.image_count
        if followup.topic and followup.topic != "飞书内容探索":
            updates["topic"] = followup.topic
        if followup.audience and followup.audience != "泛人群":
            updates["audience"] = followup.audience
        return base.model_copy(update=updates)
