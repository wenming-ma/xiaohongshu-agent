from __future__ import annotations

import asyncio
import pytest
from pathlib import Path

from src.orchestration.conversation import ConversationRequest
from src.orchestration.conversation import ContentRoute
from src.orchestration.feishu_interactions import FeishuInteractionTools, InteractionDecision
from src.orchestration.feishu_workflow import FeishuWorkflowService
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeSession:
    def __init__(self) -> None:
        self.chat_id = "chat-demo"
        self.handle = type("Handle", (), {"session_id": "session-demo"})()
        self.finished = []
        self.phases: list[str] = []

    async def ensure_active(self):
        return None

    async def update_phase(self, phase: str, *, summary: str | None = None):
        self.phases.append(phase)
        return None

    async def finish(self, *, status: str = "completed"):
        self.finished.append(status)
        return None


class FakeNotifier:
    def __init__(self, replies: list[str] | None = None, media_replies: list[tuple[Path | None, str]] | None = None) -> None:
        self.sent_messages: list[str] = []
        self.sent_cards: list[dict[str, object]] = []
        self.sent_forms: list[dict[str, object]] = []
        self.replies = list(replies or [])
        self.media_replies = list(media_replies or [])

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
        if self.media_replies:
            return self.media_replies.pop(0)
        if not self.replies:
            raise AssertionError(f"missing fake reply for phase {phase}")
        return None, self.replies.pop(0)


class LiveEventNotifier(FakeNotifier):
    def __init__(
        self,
        replies: list[str] | None = None,
        media_replies: list[tuple[Path | None, str]] | None = None,
        *,
        release_event: asyncio.Event | None = None,
    ) -> None:
        super().__init__(replies=replies, media_replies=media_replies)
        self.release_event = release_event

    async def wait_for_session_image_or_text(
        self,
        session: FakeSession,
        *,
        phase: str,
        summary: str | None = None,
    ):
        if self.release_event is not None:
            await self.release_event.wait()
            self.release_event = None
        if self.media_replies:
            return self.media_replies.pop(0)
        if self.replies:
            return None, self.replies.pop(0)
        await asyncio.Future()


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

    async def plan(self, request: ConversationRequest):
        return type("_Plan", (), {"route": request.route_hint or ContentRoute.IMAGE_POST})()


class CancellableOrchestrator(FakeOrchestrator):
    def __init__(self) -> None:
        super().__init__()
        self.first_run_started = asyncio.Event()
        self.cancelled_runs = 0

    async def run_request(
        self,
        request: ConversationRequest,
        *,
        chat_id: str | None = None,
        run_id: str | None = None,
        send_to_feishu: bool = False,
    ) -> ResultEnvelope[DeliveryPackage]:
        self.calls.append((request, chat_id))
        if len(self.calls) == 1:
            self.first_run_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.cancelled_runs += 1
                raise
        return ResultEnvelope[DeliveryPackage].success(
            agent_name="delivery",
            payload=DeliveryPackage(route="image_post", title=request.topic, summary="done"),
            summary="done",
            run_id=run_id or "run-demo",
            step_id="delivery",
        )


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


def interaction_tools_for(
    notifier: FakeNotifier,
    *,
    ask_route_choice: bool = False,
    ask_style_choices: bool = False,
) -> FeishuInteractionTools:
    return FeishuInteractionTools(
        notifier=notifier,
        route_resolver=lambda request: request.route_hint or ContentRoute.IMAGE_POST,
        interaction_decider=lambda request: InteractionDecision(
            ask_route_choice=ask_route_choice,
            ask_style_choices=ask_style_choices,
        ),
    )


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
        interaction_tools=interaction_tools_for(notifier),
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
    assert "planning" in session.phases
    assert "running_image_post" in session.phases


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
        interaction_tools=interaction_tools_for(notifier),
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
        interaction_tools=interaction_tools_for(notifier, ask_route_choice=True),
    )

    await service.handle_text("帮我做一条内容")

    request, _ = orchestrator.calls[0]
    assert request.route_hint is ContentRoute.ARTICLE_POST
    assert notifier.sent_cards
    assert ("你决定，直接开始", "__route__:auto") in notifier.sent_cards[0]["buttons"]


@pytest.mark.anyio
async def test_workflow_service_new_session_shortcut_cancels_current_request() -> None:
    session = FakeSession()
    notifier = FakeNotifier(replies=["__control__:new_session"])
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
        interaction_tools=interaction_tools_for(notifier, ask_route_choice=True),
    )

    await service.handle_text("帮我做一条内容")

    assert orchestrator.calls == []
    assert session.finished == ["cancelled"]
    assert any("新会话" in message for message in notifier.sent_messages)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "text",
    [
        "__control__:new_session",
        "control:new_session",
        "@__control__:new_session",
    ],
)
async def test_workflow_service_accepts_feishu_rewritten_new_session_shortcuts(text: str) -> None:
    notifier = FakeNotifier()
    orchestrator = FakeOrchestrator()

    async def unexpected_acquire(*, workflow: str, summary: str):
        raise AssertionError("control shortcuts should not acquire a workflow session")

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=unexpected_acquire,
        interaction_tools=interaction_tools_for(notifier),
    )

    await service.handle_text(text)

    assert orchestrator.calls == []
    assert any("新会话" in message for message in notifier.sent_messages)


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
        interaction_tools=interaction_tools_for(notifier, ask_style_choices=True),
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
        interaction_tools=interaction_tools_for(notifier),
    )

    await service.handle_text("不指定任务，让你自行探索，最后把作品发到飞书。")

    request, _ = orchestrator.calls[0]
    assert request.topic == "近期小红书高互动生活方式内容趋势"
    assert notifier.sent_cards == []
    assert notifier.sent_forms == []


@pytest.mark.anyio
async def test_workflow_service_merges_running_followup_and_restarts() -> None:
    session = FakeSession()
    orchestrator = CancellableOrchestrator()
    notifier = LiveEventNotifier(
        replies=["补充一下：两张图都必须出现帽子和水壶，还是不要人物"],
        release_event=orchestrator.first_run_started,
    )

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
        interaction_tools=interaction_tools_for(notifier),
    )

    await service.handle_text("做一条 2 张图的小红书图文，主题是春夏轻户外通勤穿搭，每张图一套穿搭，最终发飞书。")

    assert len(orchestrator.calls) == 2
    assert orchestrator.cancelled_runs == 1
    request, _ = orchestrator.calls[1]
    assert request.image_count == 2
    assert "帽子和水壶" in request.message
    assert any("已合并到当前任务" in message for message in notifier.sent_messages)
    assert session.finished == ["completed"]


@pytest.mark.anyio
async def test_workflow_service_new_session_control_cancels_running_request() -> None:
    session = FakeSession()
    orchestrator = CancellableOrchestrator()
    notifier = LiveEventNotifier(
        replies=["__control__:new_session"],
        release_event=orchestrator.first_run_started,
    )

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
        interaction_tools=interaction_tools_for(notifier),
    )

    await service.handle_text("做一条 2 张图的小红书图文，最终发飞书。")

    assert len(orchestrator.calls) == 1
    assert orchestrator.cancelled_runs == 1
    assert any("新会话" in message for message in notifier.sent_messages)
    assert session.finished == ["cancelled"]


@pytest.mark.anyio
async def test_workflow_service_turns_initial_reference_image_into_request_attachment(tmp_path: Path) -> None:
    session = FakeSession()
    reference = tmp_path / "reference-outfit.jpg"
    reference.write_bytes(b"reference")
    notifier = FakeNotifier(
        media_replies=[
            (
                None,
                "用这张参考图做 3 张通勤穿搭图文，参考图里的衣服和首饰必须出现在生成图里，背景干净，最后发飞书。",
            )
        ]
    )
    orchestrator = FakeOrchestrator()

    async def fake_acquire(*, workflow: str, summary: str):
        return session, None

    service = FeishuWorkflowService(
        notifier=notifier,
        orchestrator=orchestrator,
        acquire_session=fake_acquire,
        interaction_tools=interaction_tools_for(notifier),
    )

    await service.handle_reference_image(reference)

    request, chat_id = orchestrator.calls[0]
    assert chat_id == "chat-demo"
    assert request.reference_images == [str(reference)]
    assert request.image_count == 3
    assert "参考图" in request.message
    assert any("已收到 1 张参考图" in card["text"] for card in notifier.sent_cards)
