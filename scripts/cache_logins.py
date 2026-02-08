"""
预登录脚本 - 缓存浏览器 session

提前登录所有需要的账号，后续执行工具时无需重复登录。

使用方法:
    # 登录所有账号（小红书 + Gemini）
    uv run python scripts/cache_logins.py

    # 只登录小红书
    uv run python scripts/cache_logins.py --only xhs

    # 只登录 Gemini
    uv run python scripts/cache_logins.py --only gemini
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic_ai.mcp import MCPServerStdio
from src.tools.xiaohongshu.image_post.login import LoginAgent
from src.config.settings import PathConfig, PublishConfig, APIConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def login_xiaohongshu():
    """登录小红书并缓存 session"""
    print("=" * 60)
    print("小红书登录")
    print("=" * 60)
    print(f"Session 缓存目录: {PathConfig.BROWSER_SESSION_XHS}")
    print()

    playwright_server = MCPServerStdio(
        command='npx',
        args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
        env={
            'HEADLESS': 'false',
            'BROWSER_TYPE': 'chromium',
            'USER_DATA_DIR': PathConfig.BROWSER_SESSION_XHS
        },
        tool_prefix='playwright',
        cache_tools=True,
    )

    login_agent = LoginAgent(mcp_server=playwright_server)

    try:
        result = await login_agent.forward(
            url=PublishConfig.XHS_PUBLISH_URL,
            action="login",
            hint="小红书创作者平台，用于后续自动发布帖子"
        )

        print()
        print("-" * 40)
        if result.success:
            print(f"✅ 小红书登录成功: {result.message}")
            print(f"Session 已缓存到: {PathConfig.BROWSER_SESSION_XHS}")
        else:
            print(f"❌ 小红书登录失败: {result.message}")
        print("-" * 40)

        return result.success

    except Exception as e:
        print(f"❌ 小红书登录出错: {e}")
        import traceback
        traceback.print_exc()
        return False


async def login_gemini():
    """登录 Gemini 并缓存 session"""
    print("=" * 60)
    print("Gemini 登录")
    print("=" * 60)
    print(f"Session 缓存目录: {PathConfig.BROWSER_SESSION_GEMINI}")
    print()

    playwright_server = MCPServerStdio(
        command='npx',
        args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
        env={
            'HEADLESS': 'false',
            'BROWSER_TYPE': 'chromium',
            'USER_DATA_DIR': PathConfig.BROWSER_SESSION_GEMINI
        },
        tool_prefix='playwright',
        cache_tools=True,
    )

    login_agent = LoginAgent(mcp_server=playwright_server)

    try:
        result = await login_agent.forward(
            url=APIConfig.GEMINI_URL,
            action="login",
            hint="Gemini 平台，用于生成图片"
        )

        print()
        print("-" * 40)
        if result.success:
            print(f"✅ Gemini 登录成功: {result.message}")
            print(f"Session 已缓存到: {PathConfig.BROWSER_SESSION_GEMINI}")
        else:
            print(f"❌ Gemini 登录失败: {result.message}")
        print("-" * 40)

        return result.success

    except Exception as e:
        print(f"❌ Gemini 登录出错: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    parser = argparse.ArgumentParser(description="预登录并缓存浏览器 session")
    parser.add_argument(
        "--only",
        choices=["xhs", "gemini"],
        help="只登录指定平台（不指定则登录所有）"
    )
    args = parser.parse_args()

    print()
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 18 + "预登录脚本" + " " * 28 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    print("提示:")
    print("  - 请确保已配置 Telegram Bot (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
    print("  - 登录过程中会通过 Telegram 与你交互")
    print("  - 登录完成后 session 会保存，后续无需重复登录")
    print()

    results = {}

    if args.only == "xhs" or args.only is None:
        results["xhs"] = await login_xiaohongshu()
        print()

    if args.only == "gemini" or args.only is None:
        results["gemini"] = await login_gemini()
        print()

    print("=" * 60)
    print("登录汇总")
    print("=" * 60)
    for platform, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{platform.upper():10s} {status}")
    print("=" * 60)

    all_success = all(results.values())
    if all_success:
        print("✅ 所有账号登录完成！")
    else:
        print("⚠️  部分账号登录失败，请检查日志")


if __name__ == "__main__":
    asyncio.run(main())
