from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.utils.feishu_notifier import FeishuInputEvent, FeishuNotifier


class _FakeSessionManager:
    def __init__(self):
        self.active_state = SimpleNamespace(session_id="sess-active", status="active")
        self.control_actions: list[tuple[str, str, str]] = []

    def get_routing_state(self, chat_id: str):
        return self.active_state

    def resolve_challenger(self, *, chat_id: str, challenger_session_id: str, action: str):
        self.control_actions.append((chat_id, challenger_session_id, action))


def _build_notifier() -> FeishuNotifier:
    notifier = object.__new__(FeishuNotifier)
    notifier.client = object()
    notifier.chat_id = "chat-1"
    notifier.receive_id_type = "chat_id"
    notifier._reply_queue = asyncio.Queue()
    notifier._media_queue = asyncio.Queue()
    notifier._session_queues = {}
    notifier._session_manager = _FakeSessionManager()
    notifier._loop = None
    notifier._polling_thread = None
    notifier._session_history = []
    notifier._status_message_ids = {}
    return notifier


def test_text_events_route_to_active_session_queue_when_session_exists():
    notifier = _build_notifier()

    notifier._route_text_event(chat_id="chat-1", text="高腰阔腿裤")

    queue = notifier._session_queues["sess-active"]
    event = queue.get_nowait()
    assert event.kind == "text"
    assert event.text == "高腰阔腿裤"
    assert notifier._media_queue.empty()


def test_session_button_routes_to_matching_session_queue():
    notifier = _build_notifier()

    notifier._route_card_action_value(
        {
            "chat_id": "chat-1",
            "session_id": "sess-active",
            "phase": "style_direction",
            "keyword": "__no_style__",
        }
    )

    queue = notifier._session_queues["sess-active"]
    event = queue.get_nowait()
    assert event.kind == "button"
    assert event.text == "__no_style__"
    assert event.phase == "style_direction"


def test_control_card_action_is_resolved_by_session_manager():
    notifier = _build_notifier()

    notifier._route_card_action_value(
        {
            "chat_id": "chat-1",
            "control_action": "takeover",
            "challenger_session_id": "sess-challenger",
        }
    )

    assert notifier._session_manager.control_actions == [
        ("chat-1", "sess-challenger", "takeover")
    ]
    assert notifier._session_queues == {}


def test_session_wait_starts_polling_before_waiting_for_events():
    notifier = _build_notifier()
    started = False

    session = SimpleNamespace(
        handle=SimpleNamespace(session_id="sess-active"),
        chat_id="chat-1",
        ensure_active=lambda: asyncio.sleep(0),
        update_phase=lambda phase, summary=None: asyncio.sleep(0),
    )

    async def fake_start_polling():
        nonlocal started
        started = True
        notifier._polling_thread = object()
        notifier._get_session_queue("sess-active").put_nowait(
            FeishuInputEvent(kind="text", text="高腰阔腿裤")
        )

    notifier.start_polling = fake_start_polling

    async def _run():
        return await asyncio.wait_for(
            notifier.wait_for_session_image_or_text(
                session,
                phase="discuss_items",
            ),
            timeout=0.2,
        )

    image_path, text = asyncio.run(_run())
    assert started is True
    assert image_path is None
    assert text == "高腰阔腿裤"
