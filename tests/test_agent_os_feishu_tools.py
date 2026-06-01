from __future__ import annotations

import pytest

from src.agent_os.feishu_tools import AgentOSFeishuTools
from src.orchestration.schemas import DeliveryPackage, ResultEnvelope


class FakeTranslator:
    def __init__(self) -> None:
        self.single_choice_calls = []

    async def ask_single_choice(self, session, **kwargs):
        self.single_choice_calls.append({"session": session, **kwargs})


class FakeNotifier:
    def __init__(self) -> None:
        self.replies = ["__route__:image_post"]
        self.messages = []

    async def wait_for_session_image_or_text(self, session, **kwargs):
        return None, self.replies.pop(0)

    async def send_session_message(self, session, message, **kwargs):
        self.messages.append({"session": session, "message": message, **kwargs})


@pytest.mark.anyio
async def test_feishu_tools_ask_single_choice_uses_translator() -> None:
    translator = FakeTranslator()
    notifier = FakeNotifier()
    tools = AgentOSFeishuTools(notifier=notifier, translator=translator)

    reply = await tools.ask_single_choice(
        object(),
        title="选路线",
        options_spec="图文::image_post||文章::article_post",
        phase="clarify",
        value_prefix="__route__:",
    )

    assert reply == "__route__:image_post"
    assert translator.single_choice_calls[0]["title"] == "选路线"
    assert len(translator.single_choice_calls[0]["options"]) == 2


@pytest.mark.anyio
async def test_feishu_tools_send_delivery_summary() -> None:
    notifier = FakeNotifier()
    tools = AgentOSFeishuTools(notifier=notifier)
    envelope = ResultEnvelope[DeliveryPackage].success(
        agent_name="delivery",
        payload=DeliveryPackage(route="image_post", title="标题", summary="done"),
        summary="done",
        run_id="run-1",
        step_id="delivery",
    )

    await tools.send_delivery_summary(object(), envelope)

    assert "标题" in notifier.messages[0]["message"]
