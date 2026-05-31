from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.orchestration.conversation import ConversationRequest
from src.orchestration.session_input import ConversationInputTranslator


def test_conversation_input_translator_updates_topic_count_and_style_from_followup() -> None:
    request = ConversationRequest(
        topic="早餐酸奶碗桌面摄影",
        audience="泛人群",
        message="做 1 张早餐酸奶碗图",
        image_count=1,
        style_constraints=["真实摄影"],
    )
    translator = ConversationInputTranslator()

    updated = translator.apply(
        request,
        text="换成面试通勤穿搭，做 2 张图，风格=纯色背景,无人物,每张图只展示一套穿搭。",
    )

    assert "面试通勤穿搭" in updated.topic
    assert updated.image_count == 2
    assert "纯色背景" in updated.style_constraints
    assert "无人物" in updated.style_constraints
    assert "每张图只展示一套穿搭" in updated.style_constraints
    assert "换成面试通勤穿搭" in updated.message


def test_conversation_input_translator_adds_reference_image_as_context(tmp_path: Path) -> None:
    request = ConversationRequest(
        topic="通勤穿搭",
        audience="通勤女生",
        message="做一组通勤穿搭图",
    )
    reference = tmp_path / "reference-outfit.jpg"
    reference.write_bytes(b"image")
    translator = ConversationInputTranslator()

    updated = translator.apply(
        request,
        image_path=reference,
        text="参考这张图里的红色外套和金色项链",
    )

    assert updated.reference_images == [str(reference)]
    assert str(reference) in updated.message
    assert "红色外套" in updated.message


def test_conversation_input_translator_reports_new_session_control() -> None:
    translator = ConversationInputTranslator()

    assert translator.control_action("control:new_session") == "new_session"
    assert translator.control_action("@__control__:new_session") == "new_session"
    assert translator.control_action("普通补充") == ""


def test_conversation_input_translator_applies_structured_session_event(tmp_path: Path) -> None:
    request = ConversationRequest(
        topic="早餐酸奶碗",
        audience="泛人群",
        message="做 1 张早餐酸奶碗图",
        image_count=1,
    )
    image_path = tmp_path / "reference.jpg"
    image_path.write_bytes(b"image")
    translator = ConversationInputTranslator()

    updated = translator.apply_event(
        request,
        SimpleNamespace(kind="image", text="参考这个木勺构图", image_path=image_path),
    )

    assert updated.reference_images == [str(image_path)]
    assert "参考这个木勺构图" in updated.message
    assert str(image_path) in updated.message


def test_conversation_input_translator_reads_control_action_from_event() -> None:
    translator = ConversationInputTranslator()

    assert (
        translator.control_action_from_event(SimpleNamespace(kind="control", action="new_session"))
        == "new_session"
    )
    assert (
        translator.control_action_from_event(SimpleNamespace(kind="control", text="@__control__:new_session"))
        == "new_session"
    )
