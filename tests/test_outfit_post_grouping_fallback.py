import asyncio
from pathlib import Path

from pydantic_ai.exceptions import ModelHTTPError

from src.agents.outfit_post.image.agent import ImageAgent
from src.agents.outfit_post.schemas import ResearchItem, ResearchResult


class _FailingGroupingAgent:
    async def run(self, prompt, message_history=None):
        raise ModelHTTPError(
            status_code=503,
            model_name="bigger-model",
            body={"message": "Service temporarily unavailable", "type": "api_error"},
        )


def test_compute_groups_falls_back_to_single_group_when_grouping_model_unavailable() -> None:
    agent = ImageAgent.__new__(ImageAgent)
    agent.grouping_agent = _FailingGroupingAgent()
    agent.grouping_reviewer = None

    research = ResearchResult(
        summary="summary",
        items=[
            ResearchItem(title="look 1", content="alpha"),
            ResearchItem(title="look 2", content="beta"),
            ResearchItem(title="look 3", content="gamma"),
        ],
        keywords=[],
        sources=[],
    )

    groups = asyncio.run(agent.compute_groups(research=research, topic="休闲穿搭"))

    assert groups == [
        {
            "title": "休闲穿搭",
            "indices": [0, 1, 2],
            "ref_items": [],
        }
    ]
