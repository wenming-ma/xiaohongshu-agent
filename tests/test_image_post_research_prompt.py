from src.agents.image_post.research.prompts import (
    research_continuation_prompt,
    research_system_prompt,
    research_user_prompt,
)


def test_image_post_research_uses_rednote_browsing_domain():
    system_prompt = research_system_prompt()
    user_prompt = research_user_prompt(
        topic="胯宽腿粗怎么选裤子",
        target_audience="梨形身材女生",
        min_posts=3,
        min_key_infos=8,
        min_cases=4,
    )
    continuation_prompt = research_continuation_prompt(
        round_number=2,
        progress_snapshot="暂无",
        validation_feedback="继续研究",
        topic="胯宽腿粗怎么选裤子",
        target_audience="梨形身材女生",
        min_posts=3,
        min_key_infos=8,
        min_cases=4,
    )

    combined = "\n".join([system_prompt, user_prompt, continuation_prompt])

    assert "https://www.rednote.com" in combined
    assert "rednote.com" in combined
    assert "https://www.xiaohongshu.com" not in combined
    assert "xiaohongshu.com" not in combined


def test_image_post_research_prompt_uses_call_time_quantity_targets():
    user_prompt = research_user_prompt(
        topic="轻量化调研",
        target_audience="测试团队",
        min_posts=5,
        min_key_infos=8,
        min_cases=4,
    )
    continuation_prompt = research_continuation_prompt(
        round_number=2,
        progress_snapshot="已完成 3 个帖子",
        validation_feedback="继续",
        topic="轻量化调研",
        target_audience="测试团队",
        min_posts=5,
        min_key_infos=8,
        min_cases=4,
    )

    assert "目标收集 8+ 个内容项" in user_prompt
    assert "| 内容项 | 8 个 |" in user_prompt
    assert "内容项目标 >= 8 个" in continuation_prompt
