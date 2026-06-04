"""
预热浏览器会话 — 登录所有账号并缓存 cookie

直接启动系统 Chrome（无自动化标记），
使用共享 user-data-dir 保存登录状态。
后续 Agent 运行时通过同一 user-data-dir 复用 cookie。

重要: 运行前请先关闭所有 Chrome 窗口！

使用方法:
    uv run python scripts/warmup_sessions.py
"""
import shutil
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import PathConfig

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

SITES = [
    ("Rednote 研究访问", "https://www.rednote.com/explore"),
    ("Google 账号", "https://accounts.google.com"),
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


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    print("找不到 Chrome，请确认已安装 Google Chrome。")
    sys.exit(1)


def main():
    chrome = find_chrome()
    session_dir = str(Path(PathConfig.BROWSER_SESSION_SHARED).resolve())
    Path(session_dir).mkdir(parents=True, exist_ok=True)

    all_sites = SITES + extra_sites()
    urls = [url for _, url in all_sites]

    print("=" * 60)
    print("浏览器会话预热")
    print("=" * 60)
    print(f"Chrome: {chrome}")
    print(f"会话目录: {session_dir}")
    print()
    print("待登录站点:")
    for i, (name, url) in enumerate(all_sites):
        print(f"  {i+1}. {name} — {url}")
    print()
    print("【重要】请先关闭所有已打开的 Chrome 窗口！")
    input("准备好后按 Enter 启动 Chrome...")
    print()

    print("正在启动 Chrome（所有站点在不同标签页打开）...")
    proc = subprocess.Popen([
        chrome,
        f"--user-data-dir={session_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        *urls,
    ])

    print("Chrome 已启动，请在各标签页中依次登录。")
    print()
    input("全部登录完成后，关闭 Chrome 并按 Enter 结束...")

    proc.wait()

    print()
    print("=" * 60)
    print("会话预热完成！")
    print(f"Cookie 已缓存到: {session_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
