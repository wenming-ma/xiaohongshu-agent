"""
Playwright 浏览器管理器
用于 Deep Search 深度搜索，支持保存登录状态
"""
import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from pathlib import Path
from typing import Dict, List, Optional
import json


class PlaywrightBrowserManager:
    """
    Playwright 浏览器管理器

    特点：
    1. 持久化上下文 - 保存登录状态
    2. 自动等待 - 智能等待页面加载
    3. 错误处理 - 自动重试
    """

    def __init__(self, user_data_dir: str = "./browser-sessions"):
        """
        初始化浏览器管理器

        Args:
            user_data_dir: 保存浏览器数据的目录（cookies、登录状态等）
        """
        self.user_data_dir = Path(user_data_dir)
        self.user_data_dir.mkdir(exist_ok=True, parents=True)
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.playwright = await async_playwright().start()

        # 使用持久化上下文（保持登录状态）
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=False,  # 显示浏览器，方便首次登录和调试
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
            timezone_id="Asia/Shanghai"
        )

        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        """异步上下文管理器退出"""
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

    async def navigate(self, url: str, wait_for: str = "networkidle", timeout: int = 30000):
        """
        导航到 URL

        Args:
            url: 目标 URL
            wait_for: 等待类型 ("load", "domcontentloaded", "networkidle")
            timeout: 超时时间（毫秒）
        """
        try:
            await self.page.goto(url, wait_until=wait_for, timeout=timeout)
        except Exception as e:
            print(f"   ⚠️ 导航失败: {e}")
            # 尝试只等待 load
            await self.page.goto(url, wait_until="load", timeout=timeout)

    async def find_elements(self, selector: str, timeout: int = 5000) -> List:
        """
        查找元素

        Args:
            selector: CSS 选择器
            timeout: 超时时间（毫秒）

        Returns:
            元素列表
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return await self.page.query_selector_all(selector)
        except Exception as e:
            print(f"   ⚠️ 查找元素失败: {selector} - {e}")
            return []

    async def click(self, selector: str, timeout: int = 5000):
        """
        点击元素

        Args:
            selector: CSS 选择器
            timeout: 超时时间（毫秒）
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            await self.page.click(selector)
        except Exception as e:
            print(f"   ⚠️ 点击失败: {selector} - {e}")

    async def fill(self, selector: str, value: str, timeout: int = 5000):
        """
        填充输入框

        Args:
            selector: CSS 选择器
            value: 要填充的值
            timeout: 超时时间（毫秒）
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            await self.page.fill(selector, value)
        except Exception as e:
            print(f"   ⚠️ 填充失败: {selector} - {e}")

    async def get_text(self, selector: str, timeout: int = 5000) -> str:
        """
        获取元素文本

        Args:
            selector: CSS 选择器
            timeout: 超时时间（毫秒）

        Returns:
            元素文本，如果不存在则返回空字符串
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            element = await self.page.query_selector(selector)
            if element:
                return await element.inner_text()
        except Exception as e:
            print(f"   ⚠️ 获取文本失败: {selector} - {e}")
        return ""

    async def get_attribute(self, selector: str, attribute: str, timeout: int = 5000) -> str:
        """
        获取元素属性

        Args:
            selector: CSS 选择器
            attribute: 属性名
            timeout: 超时时间（毫秒）

        Returns:
            属性值，如果不存在则返回空字符串
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            element = await self.page.query_selector(selector)
            if element:
                value = await element.get_attribute(attribute)
                return value or ""
        except Exception as e:
            print(f"   ⚠️ 获取属性失败: {selector}.{attribute} - {e}")
        return ""

    async def screenshot(self, path: str):
        """
        截图

        Args:
            path: 保存路径
        """
        await self.page.screenshot(path=path, full_page=True)

    async def wait_for_selector(self, selector: str, timeout: int = 30000):
        """
        等待元素出现

        Args:
            selector: CSS 选择器
            timeout: 超时时间（毫秒）
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
        except Exception as e:
            print(f"   ⚠️ 等待元素超时: {selector} - {e}")

    async def scroll_to_bottom(self, scroll_count: int = 3, delay: int = 1000):
        """
        滚动到页面底部（用于加载更多内容）

        Args:
            scroll_count: 滚动次数
            delay: 每次滚动后的延迟（毫秒）
        """
        for i in range(scroll_count):
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(delay)

    async def go_back(self):
        """返回上一页"""
        await self.page.go_back()
        await self.page.wait_for_load_state("networkidle")

    async def wait(self, milliseconds: int):
        """
        等待指定时间

        Args:
            milliseconds: 毫秒
        """
        await self.page.wait_for_timeout(milliseconds)

    async def evaluate(self, script: str):
        """
        执行 JavaScript

        Args:
            script: JavaScript 代码

        Returns:
            执行结果
        """
        return await self.page.evaluate(script)

    def get_current_url(self) -> str:
        """获取当前 URL"""
        return self.page.url


# ==================== 使用示例 ====================

async def demo_playwright_browser():
    """演示 Playwright 浏览器使用"""

    print("=" * 60)
    print("Playwright 浏览器管理器演示")
    print("=" * 60)

    async with PlaywrightBrowserManager() as browser:
        # 1. 导航到小红书
        print("\n1. 导航到小红书...")
        await browser.navigate("https://www.xiaohongshu.com")
        await browser.wait(2000)

        # 2. 搜索
        print("2. 搜索关键词...")
        await browser.navigate("https://www.xiaohongshu.com/search_result?keyword=西安公司避坑")
        await browser.wait(2000)

        # 3. 查找笔记卡片
        print("3. 查找笔记卡片...")
        notes = await browser.find_elements(".note-item")
        print(f"   找到 {len(notes)} 个笔记")

        # 4. 截图
        print("4. 截图...")
        await browser.screenshot("search-result.png")
        print("   ✅ 截图已保存: search-result.png")

    print("\n" + "=" * 60)
    print("✅ 演示完成")
    print("=" * 60)


if __name__ == "__main__":
    print("""
    Playwright 浏览器管理器

    核心功能：
    1. 持久化上下文 - 保存登录状态
    2. navigate() - 导航到 URL
    3. find_elements() - 查找元素
    4. click() - 点击元素
    5. fill() - 填充输入框
    6. get_text() - 获取文本
    7. scroll_to_bottom() - 滚动加载
    8. screenshot() - 截图

    使用场景：
    - Deep Search 深度搜索
    - 浏览器自动化测试
    - 数据抓取
    """)

    # asyncio.run(demo_playwright_browser())
