from src.agents.shared.login.agent import (
    RednoteLoginAgent,
    _build_session_auth_result,
    _build_system_prompt,
    _build_user_prompt,
    _classify_web_login_text,
    _extract_state_from_report,
    _normalize_login_url,
)


def test_login_agent_prompt_requires_android_qr_without_manual_scan():
    prompt = _build_system_prompt(
        {
            "phone": "",
            "email": "",
            "username": "",
            "phone_alt": "",
            "email_alt": "",
        }
    )

    assert "try_android_qr_login_from_current_page" in prompt
    assert "check_rednote_web_login_state" in prompt
    assert "confirmation_submitted" in prompt
    assert "网页端状态" in prompt
    assert "send_current_page_screenshot" not in prompt
    assert "ask_for_user_reply" not in prompt
    assert "人工扫码" not in prompt
    assert "飞书" not in prompt


def test_login_task_prompt_mentions_android_qr_for_scan_login():
    prompt = _build_user_prompt(
        "https://www.xiaohongshu.com/explore",
        "login",
        "",
    )

    assert "Android 自动扫码" in prompt
    assert "try_android_qr_login_from_current_page" in prompt
    assert "人工扫码" not in prompt


def test_xiaohongshu_login_url_is_normalized_to_explore():
    assert _normalize_login_url("https://www.xiaohongshu.com") == "https://www.rednote.com/explore"
    assert (
        _normalize_login_url("https://creator.xiaohongshu.com/publish/publish")
        == "https://www.rednote.com/explore"
    )
    assert _normalize_login_url("https://www.rednote.com/search_result?keyword=test") == "https://www.rednote.com/explore"
    assert _normalize_login_url("https://example.com/login") == "https://example.com/login"


def test_classify_web_login_text_detects_logged_in_and_login_required():
    assert _classify_web_login_text("Explore\nNotifications\nMe\nFor you") == "logged_in"
    assert _classify_web_login_text("Log in\nScan QR code\nSign up") == "login_required"
    assert _classify_web_login_text("安全限制\nIP at risk. Switch to a secure network and retry.") == "security_error"


def test_session_state_report_short_circuits_logged_in_session():
    report = "state=logged_in\nurl=https://www.rednote.com/explore\nhint=Explore"

    assert _extract_state_from_report(report) == "logged_in"
    result = _build_session_auth_result(report, "https://www.rednote.com/explore")

    assert result is not None
    assert result.success is True
    assert result.auth_type == "session"
    assert "无需扫码" in result.message


def test_rednote_login_agent_exposes_research_access_via_single_login_entry(anyio_backend: str = "asyncio"):
    class StubRednoteLoginAgent(RednoteLoginAgent):
        def __init__(self) -> None:
            pass

        async def login(self, url: str, action: str = "login", hint: str = ""):
            self.last_call = {
                "url": url,
                "action": action,
                "hint": hint,
            }
            return "ok"

    import asyncio

    agent = StubRednoteLoginAgent()
    result = asyncio.run(agent.ensure_rednote_research_access())

    assert result == "ok"
    assert agent.last_call["url"] == "https://www.rednote.com/explore"
    assert agent.last_call["action"] == "login"
    assert "研究前检查登录态" in agent.last_call["hint"]
