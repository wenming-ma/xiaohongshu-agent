from __future__ import annotations

import pytest

from src.orchestration.conversation import ConversationRequest
from src.orchestration.conversation import ContentRoute
from src.orchestration.feishu_workflow import FeishuWorkflowService
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeSession:
    def __init__(self) -> None:
        self.chat_id = "chat-demo"
        self.handle = type("Handle", (), {"session_id": "session-demo"})()
        self.finished = []

    async def ensure_active(self):
        return None

    async def update_phase(self, phase: str, *, summary: str | None = None):
        return None

    async def finish(self, *, status: str = "completed"):
        self.finished.append(status)
        return None


class FakeNotifier:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.sent_messages: list[str] = []
        self.sent_cards: list[dict[str, object]] = []
        self.sent_forms: list[dict[str, object]] = []
        self.replies = list(replies or [])

    async def start_polling(self) -> None:
        return None

    async def send_message(self, text: str, chat_id: str | None = None) -> str:
        self.sent_messages.append(text)
        return "msg-id"

    async def send_session_message(
        self,
        session: FakeSession,
        text: str,
        *,
        phase: str | None = None,
        summary: str | None = None,
    ) -> str:
        self.sent_messages.append(text)
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
        self.sent_cards.append({"text": text, "buttons": buttons, "phase": phase})
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


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[ConversationRequest, str | None]] = []

    async def run_request(
        self,
        request: ConversationRequest,
        *,
        chat_id: str | None = None,
        run_id: str | None = None,
        send_to_feishu: bool = False,
    ) -> ResultEnvelope[DeliveryPackage]:
        self.calls.append((request, chat_id))
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery",
            payload=DeliveryPackage(route="image_post", title=request.topic, summary="done"),
            summary="done",
            run_id=run_id or "run-demo",
            step_id="delivery",
        )

    def prepare_request(self, request: ConversationRequest) -> ConversationRequest:
        if request.topic == "飞书内容探索":
            return request.model_copy(update={"topic": "近期小红书高互动生活方式内容趋势"})
        return request


class RecordingInteractionTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send_busy(self, reason: str) -> None:
        self.calls.append(f"busy:{reason}")

    async def send_session_unavailable(self) -> None:
        self.calls.append("session_unavailable")

    async def send_runtime_error(self) -> None:
        self.calls.append("runtime_error")

    async def clarify_request_if_needed(self, session: FakeSession, request: ConversationRequest):
        self.calls.append("clarify")
        return request

    async def announce_execution_started(
        self,
        session: FakeSession,
        request: ConversationRequest,
        *,
        route_label: str,
    ) -> None:
        self.calls.append(f"started:{route_label}")

    async def announce_delivery_result(self, session: FakeSession, result) -> None:
        self.calls.append(f"delivered:{result.status}")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_workflow_service_handles_one_text_request() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
    )

    await service.handle_text("任务：主题=纯色背景穿搭；受众=通勤女生；路线=image_post；风格=纯色背景,单套展示。请执行。")

    assert orchestrator.calls
    request, chat_id = orchestrator.calls[0]
    assert request.topic == "纯色背景穿搭"
    assert request.audience == "通勤女生"
    assert chat_id == "chat-demo"
    assert session.finished == ["completed"]
    assert any("已收到请求" in message for message in notifier.sent_messages)


@pytest.mark.anyio
async def test_workflow_service_delegates_user_interaction_to_tools() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    orchestrator = FakeOrchestrator()
    interactions = RecordingInteractionTools()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
        interaction_tools=interactions,
    )

    await service.handle_text("任务：主题=纯色背景穿搭；受众=通勤女生；路线=image_post；风格=纯色背景。")

    assert interactions.calls == ["clarify", "started:image_post", "delivered:success"]
    assert orchestrator.calls
    assert notifier.sent_cards == []


@pytest.mark.anyio
async def test_workflow_service_accepts_free_text_without_fixed_format() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
    )

    await service.handle_text("我想发一组通勤穿搭图片，画面要干净一点，最后发飞书。")

    assert orchestrator.calls
    request, _ = orchestrator.calls[0]
    assert "通勤穿搭" in request.topic
    assert not notifier.sent_cards


@pytest.mark.anyio
async def test_workflow_service_asks_route_with_buttons_for_sparse_request() -> None:
    session = FakeSession()
    notifier = FakeNotifier(replies=["__route__:article_post"])
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
    )

    await service.handle_text("帮我做一条内容")

    request, _ = orchestrator.calls[0]
    assert request.route_hint is ContentRoute.ARTICLE_POST
    assert notifier.sent_cards
    assert ("你决定，直接开始", "__route__:auto") in notifier.sent_cards[0]["buttons"]


@pytest.mark.anyio
async def test_workflow_service_collects_style_choices_with_multiselect_form() -> None:
    session = FakeSession()
    notifier = FakeNotifier(
        replies=[
            '__FORM__:{"style_pure_color":true,"style_single_look":true,"style_extra":"背景不要复杂"}'
        ]
    )
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
    )

    await service.handle_text("帮我做一组通勤穿搭图片")

    request, _ = orchestrator.calls[0]
    assert "纯色背景" in request.style_constraints
    assert "每张图只展示一套穿搭" in request.style_constraints
    assert "背景不要复杂" in request.style_constraints
    assert notifier.sent_forms
    assert notifier.sent_forms[0]["phase"] == "clarify_style"


@pytest.mark.anyio
async def test_workflow_service_autonomous_request_does_not_force_choices() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
    )

    await service.handle_text("不指定任务，让你自行探索，最后把作品发到飞书。")

    request, _ = orchestrator.calls[0]
    assert request.topic == "近期小红书高互动生活方式内容趋势"
    assert notifier.sent_cards == []
    assert notifier.sent_forms == []
