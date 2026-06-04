"""
一键登录研究和素材访问账号（共享浏览器缓存目录）

用途：
- 在同一个浏览器 profile 中手动登录所有站点
- 登录状态统一缓存到 PathConfig.BROWSER_SESSION_SHARED
- 后续研究、素材访问和外部资料读取复用同一份 session

使用方法：
    uv run python scripts/login_all_accounts.py
    uv run python scripts/login_all_accounts.py --sites xhs google x instagram tiktok
"""

import argparse
import io
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from src.config.settings import PathConfig


CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

SITE_MAP = {
    "xhs": ("Rednote 研究访问", "https://www.rednote.com/explore"),
    "google": ("Google 账号", "https://accounts.google.com"),
    "gemini": ("Gemini", "https://gemini.google.com/app"),
    "x": ("X (Twitter)", "https://x.com/home"),
    "instagram": ("Instagram", "https://www.instagram.com"),
    "facebook": ("Facebook", "https://www.facebook.com"),
    "tiktok": ("TikTok", "https://www.tiktok.com"),
}


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    raise FileNotFoundError("找不到 Chrome，可手动指定路径或安装 Google Chrome。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键登录所有账号并缓存到共享浏览器目录")
    parser.add_argument(
        "--sites",
        nargs="+",
        choices=list(SITE_MAP.keys()),
        default=list(SITE_MAP.keys()),
        help="指定要登录的站点（默认全部）",
    )
    parser.add_argument(
        "--force-clean-locks",
        action="store_true",
        help="启动前清理 profile 锁文件（Chrome 异常退出后推荐）",
    )
    return parser.parse_args()


def _is_chrome_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "chrome.exe" in result.stdout.lower()
    except Exception:
        return False


def _cleanup_profile_locks(session_dir: Path) -> None:
    # Chrome 使用这些文件做 profile 互斥锁；崩溃后残留会导致打开后立刻退出。
    lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    for name in lock_files:
        p = session_dir / name
        if p.exists():
            try:
                p.unlink()
                print(f"已清理锁文件: {p}")
            except Exception as e:
                print(f"清理锁文件失败: {p} ({e})")


def _is_profile_locked(session_dir: Path) -> bool:
    lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    return any((session_dir / name).exists() for name in lock_files)


def main() -> None:
    args = parse_args()
    chrome = find_chrome()
    session_path = Path(PathConfig.BROWSER_SESSION_SHARED).resolve()
    session_dir = str(session_path)
    session_path.mkdir(parents=True, exist_ok=True)

    selected_sites = [SITE_MAP[key] for key in args.sites]
    urls = [url for _, url in selected_sites]

    print("=" * 60)
    print("登录全部账号（共享缓存目录）")
    print("=" * 60)
    print(f"Chrome: {chrome}")
    print(f"缓存目录: {session_dir}")
    print()
    print("将打开以下站点：")
    for i, (name, url) in enumerate(selected_sites, start=1):
        print(f"  {i}. {name} - {url}")
    print()
    if _is_chrome_running():
        print("检测到 Chrome 正在运行。请先关闭所有 Chrome 窗口，否则可能闪退。")
    if args.force_clean_locks:
        _cleanup_profile_locks(session_path)
    print("请先关闭所有 Chrome 窗口，避免 profile 锁冲突。")
    input("准备好后按 Enter 启动 Chrome...")

    launch_cmd = [
        chrome,
        f"--user-data-dir={session_dir}",
        "--new-window",
        "--no-first-run",
        "--no-default-browser-check",
        *urls,
    ]
    print("启动命令:")
    print(" ".join(launch_cmd[:4]) + " ...")

    proc = subprocess.Popen(launch_cmd)
    # Chrome 常见行为：父进程很快退出，子进程继续运行，不能据此判定失败。
    time.sleep(2)
    running = _is_chrome_running()
    locked = _is_profile_locked(session_path)

    if running or locked:
        print("检测到 Chrome 已接管会话（进程或锁文件存在）。")
    else:
        print("未检测到明显的 Chrome 会话迹象，可能未成功启动。")
        print("可重试：先关闭全部 Chrome，再加 --force-clean-locks 运行。")

    print("Chrome 已启动（或正在后台运行）。请逐个标签页登录账号。")
    print("登录完成后，关闭 Chrome 并回到终端继续。")
    input("已完成登录并关闭 Chrome 后，按 Enter 结束...")
    proc.wait()

    print()
    print("=" * 60)
    print("完成：所有登录状态已写入共享缓存目录")
    print(f"{session_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
