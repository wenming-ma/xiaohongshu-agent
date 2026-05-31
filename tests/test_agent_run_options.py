from __future__ import annotations

from src.agents.image_post.research.agent import ResearchAgent
from src.orchestration.run_options import ResearchRunOptions


def test_image_research_agent_uses_call_time_run_options_for_validation_budget() -> None:
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.run_options = ResearchRunOptions(
        min_posts_researched=5,
        validation_max_retries=2,
        min_key_infos=6,
        min_cases=4,
    )

    agent.init_validators()

    assert agent.depth_validator.min_posts == 5
    assert agent.review_validator.min_posts == 5
    assert agent.review_validator.min_key_infos == 6
    assert agent.max_iterations == 2
