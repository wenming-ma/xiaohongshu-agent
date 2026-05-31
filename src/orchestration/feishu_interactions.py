from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from src.config.settings import RetryConfig
from src.utils.feishu_notifier import FeishuNotifier, get_feishu_notifier
from src.utils.providers import get_text_model

from .conversation import ContentRoute, ConversationRequest
from .feishu_translation import FeishuInteractionTranslator, parse_delimited_options
from .request_parser import parse_conversation_request
from .schemas import DeliveryPackage, ResultEnvelope


RouteResolver = Callable[[ConversationRequest], ContentRoute | Awaitable[ContentRoute]]


class InteractionDecision(BaseModel):
    """Agent decision for Feishu clarification UX."""

    ask_route_choice: bool = Field(
        default=False,
        description="Whether Feishu should ask the user to choose image/article/video.",
    )
    ask_style_choices: bool = Field(
        default=False,
        description="Whether Feishu should ask the user to choose image style constraints.",
    )
    rationale: str = Field(default="", description="Brief reason for the decision.")


InteractionDecider = Callable[[ConversationRequest], InteractionDecision | Awaitable[InteractionDecision]]


class FeishuSessionResetRequested(RuntimeError):
    """Raised when the Feishu activation layer asks to discard the current session."""


INTERACTION_DECISION_SYSTEM_PROMPT = """你是飞书内容系统的交互决策 Agent。

你的职责只是在用户请求进入专项 Agent 前，判断是否需要通过飞书卡片向用户追问。
不要执行内容任务，不要选择具体图片模板，不要替专项 Agent 工作。

架构准则：
- 用户可以随意表达，不要求固定格式。
- 能直接开始就不要追问；缺少关键信息且追问能显著降低误解时才追问。
- 追问只能是飞书交互墙可以承载的选择：路线选择、图片风格多选。
- 不要按关键词表触发；根据用户目标、明确程度、歧义和已有结构化字段判断。
- 输出必须符合结构化 schema。
"""


class InteractionDecisionAgent:
    """Agent-driven clarification decider for the Feishu interaction wall."""

    def __init__(self) -> None:
        self.agent = Agent(
            model=get_text_model(),
            output_type=InteractionDecision,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(INTERACTION_DECISION_SYSTEM_PROMPT,),
        )

    async def decide(self, request: ConversationRequest) -> InteractionDecision:
        payload = {
            "request": request.model_dump(mode="json"),
            "available_clarifications": [
                "route_choice: image_post / article_post / video_post / auto",
                "style_choices: pure color / single look / minimal / low saturation / free text",
            ],
        }
        result = await self.agent.run(
            "请判断这次飞书会话是否需要追问用户。\n"
            "不要使用关键词触发规则；只根据任务是否足够明确来决定。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        return result.output


class FeishuInteractionTools:
    """Feishu-facing tools used by the workflow layer for user interaction."""

    def __init__(
        self,
        *,
        notifier: FeishuNotifier | Any | None = None,
        route_resolver: RouteResolver | None = None,
        interaction_decider: InteractionDecider | None = None,
    ) -> None:
        self.notifier = notifier or get_feishu_notifier()
        self.route_resolver = route_resolver
        self.interaction_decider = interaction_decider
        self.translator = FeishuInteractionTranslator(notifier=self.notifier)
        self._decision_agent: InteractionDecisionAgent | None = None

    async def send_busy(self, reason: str) -> None:
        await self.notifier.send_message(f"当前会话忙碌中，暂时无法接管：{reason}")

    async def send_session_unavailable(self) -> None:
        await self.notifier.send_message("无法建立飞书交互会话。")

    async def send_runtime_error(self) -> None:
        await self.notifier.send_message("处理请求时发生异常，请稍后重试。")

    async def announce_session_reset(self, session: object | None = None) -> None:
        message = "已开启新会话。后续消息会作为新的主 Agent 会话输入处理。"
        if session is not None and hasattr(self.notifier, "send_session_message"):
            await self.notifier.send_session_message(
                session,
                message,
                phase="new_session",
                summary="新开会话",
            )
            return
        await self.notifier.send_message(message)

    async def clarify_request_if_needed(self, session: object, request: ConversationRequest) -> ConversationRequest:
        decision = await self._decide_interaction(request)
        if decision.ask_route_choice and request.route_hint is None:
            request = await self.ask_route_choice(session, request)

        route = request.route_hint or await self._resolve_route(request)
        if route is ContentRoute.IMAGE_POST and decision.ask_style_choices and not request.style_constraints:
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

    async def ask_single_choice_prompt(
        self,
        session: object,
        *,
        title: str,
        options_spec: str,
        phase: str,
        value_prefix: str = "",
        summary: str | None = None,
    ) -> str:
        await self.translator.ask_single_choice(
            session,
            title=title,
            options=parse_delimited_options(options_spec),
            phase=phase,
            value_prefix=value_prefix,
            summary=summary,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(
            session,
            phase=phase,
            summary=summary,
        )
        self._raise_if_control_reply(reply)
        return reply

    async def ask_multi_select_prompt(
        self,
        session: object,
        *,
        title: str,
        options_spec: str,
        phase: str,
        input_name: str = "",
        input_placeholder: str = "",
        submit_label: str = "确认",
        summary: str | None = None,
    ) -> str:
        await self.translator.ask_multi_select(
            session,
            title=title,
            options=parse_delimited_options(options_spec),
            phase=phase,
            input_name=input_name,
            input_placeholder=input_placeholder,
            submit_label=submit_label,
            summary=summary,
        )
        _, reply = await self.notifier.wait_for_session_image_or_text(
            session,
            phase=phase,
            summary=summary,
        )
        self._raise_if_control_reply(reply)
        return reply

    async def ask_route_choice(self, session: object, request: ConversationRequest) -> ConversationRequest:
        reply = await self.ask_single_choice_prompt(
            session,
            title=(
                "我先按你的话理解任务，不需要固定格式。\n\n"
                f"当前主题：{request.topic}\n"
                f"当前受众：{request.audience}\n\n"
                "这次更适合做成哪种交付？如果不想选，点“你决定”。"
            ),
            options_spec="图文::image_post||文章::article_post||视频::video_post||你决定，直接开始::auto",
            phase="clarify_route",
            value_prefix="__route__:",
            summary=request.topic,
        )
        return self._apply_route_reply(request, reply)

    async def ask_style_choices(self, session: object, request: ConversationRequest) -> ConversationRequest:
        if not hasattr(self.notifier, "send_session_form_card"):
            return request
        reply = await self.ask_multi_select_prompt(
            session,
            title=(
                "图片风格可以点选，也可以不选直接确认。\n\n"
                "我会把你选的风格作为约束交给后续 Agent。"
            ),
            options_spec=(
                "纯色背景::style_pure_color||每张图只展示一套穿搭::style_single_look||"
                "极简干净::style_minimal||低饱和高级感::style_low_saturation"
            ),
            phase="clarify_style",
            input_name="style_extra",
            input_placeholder="也可以补充一句风格要求",
            submit_label="确认这些要求",
            summary=request.topic,
        )
        return self._apply_style_reply(request, reply)

    async def collect_reference_image_request(
        self,
        session: object,
        first_image: Path,
    ) -> ConversationRequest | None:
        reference_images = [first_image]
        await self.notifier.send_session_card_message(
            session,
            (
                "已收到 1 张参考图。\n\n"
                "你可以继续发送参考图，或直接发送这组图片/帖子的需求。"
                "我会把参考图作为约束交给后续 Agent，生成图必须包含参考图里的核心物品。"
            ),
            [
                ("取消", "__reference__:cancel"),
            ],
            phase="collect_reference",
            summary="等待参考图需求",
        )

        while True:
            image_path, reply = await self.notifier.wait_for_session_image_or_text(
                session,
                phase="collect_reference",
                summary=f"已收集 {len(reference_images)} 张参考图",
            )
            if image_path is not None:
                reference_images.append(image_path)
                await self.notifier.send_session_message(
                    session,
                    f"已收到 {len(reference_images)} 张参考图。继续发图，或直接发送需求文本。",
                    phase="collect_reference",
                    summary=f"已收集 {len(reference_images)} 张参考图",
                )
                continue

            text = reply.strip()
            if not text:
                continue
            self._raise_if_control_reply(text)
            if text == "__reference__:cancel":
                return None

            request = parse_conversation_request(text)
            return request.model_copy(
                update={"reference_images": [str(path) for path in reference_images]}
            )

    async def _decide_interaction(self, request: ConversationRequest) -> InteractionDecision:
        if self.interaction_decider is not None:
            result = self.interaction_decider(request)
            if isawaitable(result):
                return await result
            return result
        if self._decision_agent is None:
            self._decision_agent = InteractionDecisionAgent()
        return await self._decision_agent.decide(request)

    async def _resolve_route(self, request: ConversationRequest) -> ContentRoute:
        if self.route_resolver is not None:
            result = self.route_resolver(request)
            if isawaitable(result):
                return await result
            return result
        return self._infer_route_for_clarification(request)

    def _infer_route_for_clarification(self, request: ConversationRequest) -> ContentRoute:
        return ContentRoute.IMAGE_POST

    def _apply_route_reply(self, request: ConversationRequest, reply: str) -> ConversationRequest:
        text = reply.strip()
        self._raise_if_control_reply(text)
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
        self._raise_if_control_reply(text)
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

    def _raise_if_control_reply(self, text: str) -> None:
        if text.strip() == "__control__:new_session":
            raise FeishuSessionResetRequested("new_session")

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
