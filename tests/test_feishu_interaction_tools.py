from __future__ import annotations

import pytest

from src.orchestration.conversation import ContentRoute, ConversationRequest
from src.orchestration.feishu_interactions import (
    FeishuInteractionTools,
    FeishuSessionResetRequested,
    InteractionDecision,
)
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeSession:
    def __init__(self) -> None:
        self.chat_id = "chat-demo"
        self.handle = type("Handle", (), {"session_id": "session-demo"})()

    async def ensure_active(self):
        return None

    async def update_phase(self, phase: str, *, summary: str | None = None):
        return None


class FakeNotifier:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.sent_cards: list[dict[str, object]] = []
        self.sent_forms: list[dict[str, object]] = []
        self.replies = list(replies or [])

    async def send_message(self, text: str, chat_id: str | None = None) -> str:
        self.sent_messages.append({"text": text, "chat_id": chat_id})
        return "msg-id"

    async def send_session_message(
        self,
        session: FakeSession,
        text: str,
        *,
        phase: str | None = None,
        summary: str | None = None,
    ) -> str:
        self.sent_messages.append({"text": text, "phase": phase, "summary": summary})
        return "msg-id"

    async def send_session_card_message(
        self,
        session: FakeSession,
        text: str,
        buttons: list[tuple[str, str]],
        *,
        phase: str,
        summary: str | None = None,
    ) -> str:
        self.sent_cards.append({"text": text, "buttons": buttons, "phase": phase, "summary": summary})
        return "card-id"

    async def send_session_form_card(
        self,
        session: FakeSession,
        title: str,
        checkers: list[dict],
        *,
        phase: str,
        input_name: str = "",
        input_placeholder: str = "",
        submit_label: str = "确认",
        summary: str | None = None,
    ) -> str:
        self.sent_forms.append(
            {
                "title": title,
                "checkers": checkers,
                "phase": phase,
                "input_name": input_name,
                "submit_label": submit_label,
            }
        )
        return "form-id"

    async def wait_for_session_image_or_text(
        self,
        session: FakeSession,
        *,
        phase: str,
        summary: str | None = None,
    ):
        if not self.replies:
            raise AssertionError(f"missing fake reply for phase {phase}")
        return None, self.replies.pop(0)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_interaction_tools_delegates_clarification_decision_without_keyword_rules() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    decision_calls: list[ConversationRequest] = []

    async def decide(request: ConversationRequest) -> InteractionDecision:
        decision_calls.append(request)
        return InteractionDecision(
            ask_route_choice=False,
            ask_style_choices=False,
            rationale="Planner has enough context to proceed.",
        )

    tools = FeishuInteractionTools(
        notifier=notifier,
        interaction_decider=decide,
        route_resolver=lambda request: ContentRoute.IMAGE_POST,
    )

    request = ConversationRequest(topic="内容", audience="泛人群", message="帮我做一条内容")

    clarified = await tools.clarify_request_if_needed(session, request)

    assert clarified == request
    assert decision_calls == [request]
    assert notifier.sent_cards == []
    assert notifier.sent_forms == []


@pytest.mark.anyio
async def test_interaction_tools_asks_choices_only_when_decider_requests_them() -> None:
    session = FakeSession()
    notifier = FakeNotifier(
        replies=[
            "__route__:image_post",
            '__FORM__:{"style_pure_color":true,"style_single_look":true}',
        ]
    )

    async def decide(request: ConversationRequest) -> InteractionDecision:
        return InteractionDecision(
            ask_route_choice=True,
            ask_style_choices=True,
            rationale="User asked for an image post but needs route/style confirmation.",
        )

    tools = FeishuInteractionTools(
        notifier=notifier,
        interaction_decider=decide,
        route_resolver=lambda request: ContentRoute.IMAGE_POST,
    )

    request = ConversationRequest(
        topic="明确的图文任务",
        audience="泛人群",
        message="请直接做图文，正常情况下旧关键词规则不会追问路线。",
    )

    clarified = await tools.clarify_request_if_needed(session, request)

    assert clarified.route_hint is ContentRoute.IMAGE_POST
    assert "纯色背景" in clarified.style_constraints
    assert "每张图只展示一套穿搭" in clarified.style_constraints
    assert len(notifier.sent_cards) == 1
    assert len(notifier.sent_forms) == 1


@pytest.mark.anyio
async def test_interaction_tools_exposes_generic_choice_prompt_primitive() -> None:
    session = FakeSession()
    notifier = FakeNotifier(replies=["__priority__:when_idle"])
    tools = FeishuInteractionTools(notifier=notifier)

    reply = await tools.ask_single_choice_prompt(
        session,
        title="这条用户消息怎么处理？",
        options_spec="立即中断::interrupt||当前任务后处理::when_idle",
        phase="control_priority",
        value_prefix="__priority__:",
        summary="消息插入时机",
    )

    assert reply == "__priority__:when_idle"
    assert notifier.sent_cards[0]["buttons"] == [
        ("立即中断", "__priority__:interrupt"),
        ("当前任务后处理", "__priority__:when_idle"),
    ]


@pytest.mark.anyio
async def test_interaction_tools_exposes_generic_multiselect_prompt_primitive() -> None:
    session = FakeSession()
    notifier = FakeNotifier(replies=['__FORM__:{"flatlay":true,"no_people":true}'])
    tools = FeishuInteractionTools(notifier=notifier)

    reply = await tools.ask_multi_select_prompt(
        session,
        title="请选择图片约束",
        options_spec="平铺::flatlay||不要人物::no_people",
        phase="image_constraints",
        input_name="extra",
        summary="图片约束",
    )

    assert reply == '__FORM__:{"flatlay":true,"no_people":true}'
    assert notifier.sent_forms[0]["checkers"] == [
        {"name": "flatlay", "text": "平铺", "checked": False},
        {"name": "no_people", "text": "不要人物", "checked": False},
    ]


@pytest.mark.anyio
async def test_interaction_tools_clarify_route_with_choice_card() -> None:
    session = FakeSession()
    notifier = FakeNotifier(replies=["__route__:video_post"])
    tools = FeishuInteractionTools(
        notifier=notifier,
        interaction_decider=lambda request: InteractionDecision(ask_route_choice=True),
    )

    request = ConversationRequest(topic="内容", audience="泛人群", message="帮我做一条内容")

    clarified = await tools.clarify_request_if_needed(session, request)

    assert clarified.route_hint is ContentRoute.VIDEO_POST
    assert notifier.sent_cards
    assert ("你决定，直接开始", "__route__:auto") in notifier.sent_cards[0]["buttons"]


@pytest.mark.anyio
async def test_interaction_tools_collect_style_choices_with_form() -> None:
    session = FakeSession()
    notifier = FakeNotifier(
        replies=['__FORM__:{"style_pure_color":true,"style_single_look":true,"style_extra":"不要人物"}']
    )
    tools = FeishuInteractionTools(
        notifier=notifier,
        interaction_decider=lambda request: InteractionDecision(ask_style_choices=True),
        route_resolver=lambda request: ContentRoute.IMAGE_POST,
    )

    request = ConversationRequest(topic="通勤穿搭图片", audience="泛人群", message="帮我做一组通勤穿搭图片")

    clarified = await tools.clarify_request_if_needed(session, request)

    assert "纯色背景" in clarified.style_constraints
    assert "每张图只展示一套穿搭" in clarified.style_constraints
    assert "不要人物" in clarified.style_constraints
    assert notifier.sent_forms
    assert notifier.sent_forms[0]["phase"] == "clarify_style"


@pytest.mark.anyio
async def test_interaction_tools_new_session_control_raises_reset_request() -> None:
    session = FakeSession()
    notifier = FakeNotifier(replies=["__control__:new_session"])
    tools = FeishuInteractionTools(
        notifier=notifier,
        interaction_decider=lambda request: InteractionDecision(ask_route_choice=True),
    )

    request = ConversationRequest(topic="内容", audience="泛人群", message="帮我做一条内容")

    with pytest.raises(FeishuSessionResetRequested):
        await tools.clarify_request_if_needed(session, request)


@pytest.mark.anyio
async def test_interaction_tools_wrap_status_and_delivery_messages() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    tools = FeishuInteractionTools(notifier=notifier)
    request = ConversationRequest(
        topic="登山穿搭",
        audience="户外新人",
        message="做 5 张图",
        route_hint=ContentRoute.IMAGE_POST,
    )
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery",
        payload=DeliveryPackage(route="image_post", title="登山穿搭 5 图", summary="done"),
        summary="done",
        run_id="run-demo",
        step_id="delivery",
    )

    await tools.announce_execution_started(session, request, route_label="image_post")
    await tools.announce_delivery_result(session, envelope)

    assert any("已收到请求" in str(message["text"]) for message in notifier.sent_messages)
    assert any("登山穿搭 5 图" in str(message["text"]) for message in notifier.sent_messages)
