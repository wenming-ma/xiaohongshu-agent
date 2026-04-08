import asyncio
from pathlib import Path

from src.agents.outfit_post.discuss.agent import DiscussAgent
from src.agents.outfit_post.schemas import OutfitItem


class _FakeNotifier:
    def __init__(self, replies):
        self.client = object()
        self._replies = list(replies)
        self.sent_messages = []
        self.sent_cards = []

    async def send_message(self, text: str, *args, **kwargs):
        self.sent_messages.append(text)
        return "msg"

    async def send_card_message_raw(self, card: dict, *args, **kwargs):
        self.sent_cards.append(card)
        return "card"

    async def wait_for_image_or_text(self):
        if not self._replies:
            raise AssertionError("No more fake replies")
        return self._replies.pop(0)


class _QueueAwareFakeNotifier(_FakeNotifier):
    def __init__(self, replies):
        super().__init__(replies)
        self.clear_queue_called = 0

    def clear_queue(self):
        self.clear_queue_called += 1
        while self._replies and self._replies[0][0] is not None:
            self._replies.pop(0)

    async def send_card_message(self, text: str, buttons, *args, **kwargs):
        self.sent_cards.append({"text": text, "buttons": buttons})
        return "card"


class _CollectImagesFakeNotifier(_QueueAwareFakeNotifier):
    def __init__(self, responses):
        super().__init__([])
        self._collect_responses = list(responses)
        self.collect_prompts = []

    async def collect_images(self, **kwargs):
        self.collect_prompts.append(kwargs["prompt"])
        if not self._collect_responses:
            raise AssertionError("No more fake collect_images responses")
        return self._collect_responses.pop(0)


def test_discuss_items_accumulates_multiple_text_messages_before_confirm():
    agent = DiscussAgent()
    agent.notifier = _FakeNotifier([
        (None, "白色衬衫"),
        (None, "高腰阔腿裤"),
        (None, "小白鞋"),
        (None, "确认列表"),
        (None, "确认列表"),
    ])

    async def _fake_parse(text: str):
        return [OutfitItem(name=text.strip())]

    agent._parse_items = _fake_parse

    items = asyncio.run(agent.discuss_items())

    assert [item.name for item in items] == ["白色衬衫", "高腰阔腿裤", "小白鞋"]
    assert len(agent.notifier.sent_cards) >= 1


def test_discuss_items_clears_stale_media_queue_before_new_run():
    agent = DiscussAgent()
    agent.notifier = _QueueAwareFakeNotifier([
        (Path("/tmp/stale.jpg"), ""),
        (None, "白色衬衫"),
        (None, "确认列表"),
    ])

    async def _fake_parse(text: str):
        return [OutfitItem(name=text.strip())]

    agent._parse_items = _fake_parse

    items = asyncio.run(agent.discuss_items())

    assert [item.name for item in items] == ["白色衬衫"]
    assert agent.notifier.clear_queue_called == 1
    assert all("请先用文字告诉我搭配包含哪些单品" not in msg for msg in agent.notifier.sent_messages)


def test_ask_style_direction_clears_stale_media_queue_before_waiting_for_choice():
    agent = DiscussAgent()
    agent.notifier = _QueueAwareFakeNotifier([
        (Path("/tmp/stale.jpg"), ""),
        (None, "法式通勤"),
    ])

    class _FakeStyleSuggester:
        async def run(self, prompt):
            class _Result:
                output = type(
                    "_Suggestion",
                    (),
                    {
                        "options": [
                            type("_Option", (), {"label": "法式通勤", "keyword": "法式通勤"})(),
                        ]
                    },
                )()

            return _Result()

    agent.style_suggester = _FakeStyleSuggester()

    selected = asyncio.run(agent.ask_style_direction([OutfitItem(name="白色衬衫")]))

    assert selected == "法式通勤"
    assert agent.notifier.clear_queue_called == 1
    assert all("请先选择风格方向" not in msg for msg in agent.notifier.sent_messages)


def test_collect_images_clears_stale_queue_before_each_item_prompt():
    agent = DiscussAgent()
    agent.notifier = _CollectImagesFakeNotifier([
        ([Path("/tmp/hat.jpg")], "next"),
        ([Path("/tmp/shoes.jpg")], "done"),
    ])

    result = asyncio.run(
        agent.collect_images(
            items=[OutfitItem(name="帽子"), OutfitItem(name="鞋子")],
            ref_dir=Path("/tmp/reference_images"),
        )
    )

    assert [item.item_name for item in result] == ["帽子", "鞋子"]
    assert agent.notifier.clear_queue_called == 2
