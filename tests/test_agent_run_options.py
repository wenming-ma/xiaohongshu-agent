from __future__ import annotations

import asyncio

from src.agents.image_post.research.agent import ResearchAgent
from src.agents.image_post.research.state import ResearchState
from src.agents.image_post.schemas import ContentSource, ResearchItem, ResearchResult
from src.orchestration.run_options import ResearchRunOptions


def test_image_research_agent_uses_call_time_run_options_for_validation_budget() -> None:
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.run_options = ResearchRunOptions(
        min_posts_researched=5,
        validation_max_retries=2,
        min_key_infos=6,
        min_cases=4,
        max_new_posts_per_iteration=2,
        per_iteration_request_limit=11,
        per_iteration_tool_calls_limit=22,
    )

    agent.init_validators()

    assert agent.depth_validator.min_posts == 5
    assert agent.review_validator.min_posts == 5
    assert agent.review_validator.min_key_infos == 6
    assert agent.max_iterations == 2
    assert agent._run_options().max_new_posts_per_iteration == 2
    assert agent._run_options().per_iteration_request_limit == 11
    assert agent._run_options().per_iteration_tool_calls_limit == 22


def _research_result() -> ResearchResult:
    return ResearchResult(
        summary="测试研究结果",
        items=[
            ResearchItem(title="酸奶碗元素", content="蓝莓、草莓、燕麦和木勺是画面核心", source_ref="post_1")
        ],
        keywords=["酸奶碗"],
        sources=[ContentSource(url="https://www.rednote.com/explore/1", title="酸奶碗", domain="rednote.com")],
    )


def test_image_research_agent_applies_per_iteration_usage_limits() -> None:
    captured = {}

    class FakeGenerator:
        async def run(self, prompt, *, usage_limits):
            captured["prompt"] = prompt
            captured["usage_limits"] = usage_limits

            class Result:
                output = _research_result()

            return Result()

    agent = ResearchAgent.__new__(ResearchAgent)
    agent.run_options = ResearchRunOptions(
        min_posts_researched=3,
        validation_max_retries=2,
        min_key_infos=5,
        min_cases=1,
        per_iteration_request_limit=9,
        per_iteration_tool_calls_limit=17,
    )
    agent.max_iterations = 2
    agent.generator = FakeGenerator()

    class FakeNavigateTracker:
        def get_stats(self):
            return {"post_detail_count": 1, "post_detail_urls": ["https://www.rednote.com/explore/1"]}

    agent.navigate_tracker = FakeNavigateTracker()

    state = ResearchState(topic="早餐酸奶碗", target_audience="小红书用户", output_dir=None)
    asyncio.run(agent.step(state, 0))

    assert state.current_result == _research_result()
    assert captured["usage_limits"].request_limit == 9
    assert captured["usage_limits"].tool_calls_limit == 17
    assert "本轮最多进入 3 个高热帖子" in captured["prompt"]


def test_image_research_continuation_prompt_has_targeted_budget(tmp_path) -> None:
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.run_options = ResearchRunOptions(
        min_posts_researched=5,
        validation_max_retries=2,
        min_key_infos=5,
        min_cases=1,
        max_new_posts_per_iteration=2,
    )
    state = ResearchState(topic="早餐酸奶碗", target_audience="小红书用户", output_dir=tmp_path)
    state.current_result = _research_result()
    state.tracked_stats = {
        "post_detail_count": 5,
        "post_detail_urls": ["https://www.rednote.com/explore/1"],
    }

    agent.on_validation_failed(state, 0, "评论区数据不足")

    assert "历史已进入帖子详情页：5 个" in state.continuation_prompt
    assert "距离最低要求还差：0 个" in state.continuation_prompt
    assert "本轮最多新增进入 2 个帖子详情页" in state.continuation_prompt
    assert "针对验证反馈做定向补齐" in state.continuation_prompt
