from __future__ import annotations

import pytest

from src.orchestration.feishu_translation import (
    FeishuInteractionTranslator,
    parse_delimited_options,
)


class FakeSession:
    def __init__(self) -> None:
        self.chat_id = "chat-demo"
        self.handle = type("Handle", (), {"session_id": "session-demo"})()

    async def ensure_active(self):
        return None

    async def update_phase(self, phase: str, *, summary: str | None = None):
        return None


class FakeNotifier:
    def __init__(self) -> None:
        self.sent_cards: list[dict[str, object]] = []
        self.sent_forms: list[dict[str, object]] = []

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
                "input_placeholder": input_placeholder,
                "submit_label": submit_label,
                "summary": summary,
            }
        )
        return "form-id"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_parse_delimited_options_keeps_tool_payload_simple() -> None:
    options = parse_delimited_options("图文::image_post||文章::article_post||你决定::auto")

    assert [(item.label, item.value) for item in options] == [
        ("图文", "image_post"),
        ("文章", "article_post"),
        ("你决定", "auto"),
    ]


@pytest.mark.anyio
async def test_translator_renders_single_choice_tool_call_as_feishu_buttons() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    translator = FeishuInteractionTranslator(notifier=notifier)

    await translator.ask_single_choice(
        session,
        title="这次更适合做哪种交付？",
        options=parse_delimited_options("图文::image_post||文章::article_post"),
        phase="clarify_route",
        value_prefix="__route__:",
        summary="内容路线",
    )

    assert notifier.sent_cards == [
        {
            "text": "这次更适合做哪种交付？",
            "buttons": [("图文", "__route__:image_post"), ("文章", "__route__:article_post")],
            "phase": "clarify_route",
            "summary": "内容路线",
        }
    ]


@pytest.mark.anyio
async def test_translator_renders_multiselect_tool_call_as_feishu_form() -> None:
    session = FakeSession()
    notifier = FakeNotifier()
    translator = FeishuInteractionTranslator(notifier=notifier)

    await translator.ask_multi_select(
        session,
        title="请选择图片风格",
        options=parse_delimited_options("纯色背景::style_pure_color||不要人物::style_no_people"),
        phase="clarify_style",
        input_name="style_extra",
        input_placeholder="也可以补充一句",
        submit_label="确认风格",
        summary="风格约束",
    )

    assert notifier.sent_forms
    form = notifier.sent_forms[0]
    assert form["title"] == "请选择图片风格"
    assert form["phase"] == "clarify_style"
    assert form["input_name"] == "style_extra"
    assert form["submit_label"] == "确认风格"
    assert form["checkers"] == [
        {"name": "style_pure_color", "text": "纯色背景", "checked": False},
        {"name": "style_no_people", "text": "不要人物", "checked": False},
    ]
