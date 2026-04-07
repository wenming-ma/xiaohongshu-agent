import asyncio

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


def test_discuss_items_accumulates_multiple_text_messages_before_confirm():
    agent = DiscussAgent()
    agent.notifier = _FakeNotifier([
        (None, "白色衬衫"),
        (None, "高腰阔腿裤"),
        (None, "小白鞋"),
        (None, "确认列表"),  # 进入确认卡片阶段
        (None, "确认列表"),  # 在确认卡片里确认
    ])

    async def _fake_parse(text: str):
        return [OutfitItem(name=text.strip())]

    agent._parse_items = _fake_parse

    items = asyncio.run(agent.discuss_items())

    assert [item.name for item in items] == ["白色衬衫", "高腰阔腿裤", "小白鞋"]
    assert len(agent.notifier.sent_cards) >= 1
