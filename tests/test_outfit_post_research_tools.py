import asyncio

from src.agents.outfit_post.research.tools import PostImageReaderAgent


class _FakeVisionAgent:
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def run(self, payload):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return "ok"


def test_post_image_reader_limits_vision_concurrency() -> None:
    agent = PostImageReaderAgent.__new__(PostImageReaderAgent)
    agent._vision_agent = _FakeVisionAgent()
    agent._vision_semaphore = asyncio.Semaphore(3)

    async def _run_many():
        tasks = [agent._run_vision_with_limit(None) for _ in range(15)]
        await asyncio.gather(*tasks)

    asyncio.run(_run_many())

    assert agent._vision_agent.max_active <= 3
