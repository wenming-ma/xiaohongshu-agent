from src.agents.shared.utils.playwright_artifacts import sanitize_playwright_filename


def test_sanitize_playwright_filename_strips_directory_segments() -> None:
    args = {"filename": r"output\playwright-downloads\post_1_main.png", "type": "png"}

    sanitized = sanitize_playwright_filename("browser_take_screenshot", args)

    assert sanitized["filename"] == "post_1_main.png"


def test_sanitize_playwright_filename_adds_missing_screenshot_extension() -> None:
    args = {"filename": "post_fang_lian", "type": "png"}

    sanitized = sanitize_playwright_filename("browser_take_screenshot", args)

    assert sanitized["filename"] == "post_fang_lian.png"


def test_sanitize_playwright_filename_keeps_non_filename_tools_unchanged() -> None:
    args = {"url": "https://www.xiaohongshu.com"}

    sanitized = sanitize_playwright_filename("browser_navigate", args)

    assert sanitized == args
