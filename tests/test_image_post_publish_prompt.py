from src.agents.image_post.publish.prompts import publisher_system_prompt


def test_image_post_publisher_uses_explore_for_login_tool():
    prompt = publisher_system_prompt()

    assert 'login(url="https://www.rednote.com/explore", action="login"' in prompt
    assert "登录完成后，再导航回 https://creator.xiaohongshu.com/publish/publish" in prompt
