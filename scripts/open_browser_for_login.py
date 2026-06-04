"""
打开浏览器手动登录账号（使用 Playwright Chromium）

用途：
- 使用 Playwright 的 Chromium 打开浏览器（不会与系统 Chrome 冲突）
- 登录状态缓存到 PathConfig.BROWSER_SESSION_SHARED
- 后续所有流程复用同一份 session

使用方法：
    uv run python scripts/open_browser_for_login.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
from src.config.settings import PathConfig


SITES = [
    ("Google 账号", "https://accounts.google.com"),
    ("Rednote 研究访问", "https://www.rednote.com/explore"),
    ("Medium", "https://medium.com"),
    ("Allure", "https://www.allure.com"),
    ("Byrdie", "https://www.byrdie.com"),
    ("Who What Wear", "https://www.whowhatwear.com"),
    ("X (Twitter)", "https://x.com/home"),
    ("TikTok", "https://www.tiktok.com"),
]


def extra_sites() -> list[tuple[str, str]]:
    raw = os.getenv("ARTICLE_LOGIN_URLS", "")
    sites: list[tuple[str, str]] = []
    for idx, url in enumerate((item.strip() for item in raw.split(",")), start=1):
        if url:
            sites.append((f"自定义站点 {idx}", url))
    return sites


async def main():
    session_dir = str(Path(PathConfig.BROWSER_SESSION_SHARED).resolve())
    Path(session_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("打开浏览器登录账号")
    print("=" * 60)
    print(f"Session 缓存目录: {session_dir}")
    print()
    all_sites = SITES + extra_sites()

    print("将打开以下站点：")
    for i, (name, url) in enumerate(all_sites, start=1):
        print(f"  {i}. {name} - {url}")
    print()
    print("请在浏览器中逐个标签页登录你的账号。")
    print("登录完成后，手动关闭浏览器窗口即可保存 session。")
    print("=" * 60)
    print()

    async with async_playwright() as p:
        # 使用 persistent context 保存登录状态
        context = await p.chromium.launch_persistent_context(
            user_data_dir=session_dir,
            headless=False,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
            no_viewport=True,
        )

        # 打开所有站点
        for name, url in all_sites:
            page = await context.new_page()
            await page.goto(url)
            print(f"已打开: {name}")

        # 关闭默认空白页
        pages = context.pages
        if len(pages) > len(all_sites) and pages[0].url == "about:blank":
            await pages[0].close()

        print()
        print("浏览器已打开，请手动登录各个平台。")
        print("登录完成后，直接关闭浏览器窗口即可。")
        print()

        while True:
            await asyncio.sleep(1)
            try:
                open_pages = [page for page in context.pages if not page.is_closed()]
            except Exception:
                break
            if not open_pages:
                break

        try:
            await context.close()
        except Exception:
            pass

    print()
    print("=" * 60)
    print("完成：登录状态已保存")
    print(f"缓存目录: {session_dir}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
