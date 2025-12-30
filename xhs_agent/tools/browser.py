"""
浏览器自动化工具 - 使用 Playwright
支持小红书内容发布
"""
import asyncio
from pathlib import Path
from typing import Dict, List, Any
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout

from config import XHS_CONFIG


class BrowserAutomation:
    """浏览器自动化基类"""

    def __init__(self, headless: bool = False):
        """
        初始化浏览器自动化

        Args:
            headless: 是否无头模式（False便于调试）
        """
        self.headless = headless
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.playwright = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()

    async def start(self):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',  # 反检测
                '--no-sandbox',
                '--disable-dev-shm-usage'
            ]
        )

        # 创建浏览器上下文（带反检测）
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # 注入反检测脚本
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        self.page = await context.new_page()

    async def close(self):
        """关闭浏览器"""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def wait_for_load(self, timeout: int = 30000):
        """等待页面加载完成"""
        if self.page:
            await self.page.wait_for_load_state('networkidle', timeout=timeout)

    async def screenshot(self, path: str):
        """截图"""
        if self.page:
            await self.page.screenshot(path=path, full_page=True)


class XiaohongshuPublisher(BrowserAutomation):
    """小红书发布器"""

    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self.login_url = XHS_CONFIG["login_url"]
        self.publish_url = XHS_CONFIG["publish_url"]

    async def login_interactive(self) -> bool:
        """
        交互式登录
        让用户手动扫码登录，然后保存session

        Returns:
            是否登录成功
        """
        if not self.page:
            raise RuntimeError("Browser not started. Call start() first.")

        print("🔐 正在打开小红书登录页面...")
        await self.page.goto(self.login_url)

        print("\n⏳ 请在浏览器中扫码登录小红书...")
        print("   登录成功后，按 Enter 继续...\n")

        # 等待用户手动登录
        input("按 Enter 继续 >>>")

        # 检查是否登录成功（通过检查用户头像或其他元素）
        try:
            # 尝试访问创作中心
            await self.page.goto("https://creator.xiaohongshu.com/")
            await self.page.wait_for_selector('text=创作灵感', timeout=5000)
            print("✅ 登录成功！")
            return True
        except PlaywrightTimeout:
            print("❌ 登录失败或超时")
            return False

    async def save_session(self, path: str = ".xhs_session.json"):
        """
        保存登录session到文件

        Args:
            path: session文件路径
        """
        if not self.page:
            raise RuntimeError("No active page")

        storage_state = await self.page.context.storage_state(path=path)
        print(f"💾 Session已保存到: {path}")
        return storage_state

    async def load_session(self, path: str = ".xhs_session.json") -> bool:
        """
        从文件加载登录session

        Args:
            path: session文件路径

        Returns:
            是否加载成功
        """
        session_file = Path(path)
        if not session_file.exists():
            print(f"⚠️  Session文件不存在: {path}")
            return False

        # 重新创建带session的上下文
        if self.browser:
            context = await self.browser.new_context(storage_state=path)
            if self.page:
                await self.page.close()
            self.page = await context.new_page()
            print(f"✅ Session已加载: {path}")
            return True
        return False

    async def publish_post(
        self,
        title: str,
        content: str,
        images: List[str],
        hashtags: List[str]
    ) -> Dict[str, Any]:
        """
        发布小红书笔记

        Args:
            title: 标题
            content: 正文内容
            images: 图片路径列表（按顺序）
            hashtags: 话题标签列表

        Returns:
            发布结果字典
        """
        if not self.page:
            raise RuntimeError("Browser not started")

        try:
            # 1. 导航到发布页面
            print("📝 正在打开发布页面...")
            await self.page.goto(self.publish_url)
            await asyncio.sleep(2)

            # 2. 上传图片（处理文件选择器）
            print(f"📸 正在上传 {len(images)} 张图片...")
            for idx, image_path in enumerate(images):
                if not Path(image_path).exists():
                    print(f"⚠️  图片不存在，跳过: {image_path}")
                    continue

                # 查找上传按钮并上传
                try:
                    # 小红书使用 input[type="file"] 进行文件上传
                    file_input = await self.page.wait_for_selector(
                        'input[type="file"]',
                        timeout=5000
                    )
                    await file_input.set_input_files(image_path)
                    print(f"  ✓ 已上传图片 {idx + 1}/{len(images)}")
                    await asyncio.sleep(1)
                except PlaywrightTimeout:
                    print(f"  ✗ 上传图片失败: {image_path}")

            await asyncio.sleep(2)

            # 3. 填写标题
            print("✍️  正在填写标题...")
            try:
                title_input = await self.page.wait_for_selector(
                    'input[placeholder*="标题"], input[placeholder*="title"]',
                    timeout=5000
                )
                await title_input.fill(title)
                print(f"  ✓ 标题: {title}")
            except PlaywrightTimeout:
                print("  ⚠️  未找到标题输入框")

            # 4. 填写正文
            print("✍️  正在填写正文...")
            try:
                # 小红书可能使用 contenteditable 或 textarea
                content_selector = (
                    'div[contenteditable="true"], '
                    'textarea[placeholder*="正文"], '
                    'textarea[placeholder*="内容"]'
                )
                content_input = await self.page.wait_for_selector(
                    content_selector,
                    timeout=5000
                )
                await content_input.fill(content)
                print(f"  ✓ 正文长度: {len(content)} 字")
            except PlaywrightTimeout:
                print("  ⚠️  未找到正文输入框")

            # 5. 添加话题标签
            if hashtags:
                print(f"🏷️  正在添加 {len(hashtags)} 个标签...")
                for tag in hashtags:
                    try:
                        # 小红书话题输入
                        hashtag_input = await self.page.wait_for_selector(
                            'input[placeholder*="话题"], input[placeholder*="标签"]',
                            timeout=3000
                        )
                        await hashtag_input.fill(f"#{tag}")
                        await self.page.keyboard.press('Enter')
                        await asyncio.sleep(0.5)
                        print(f"  ✓ 已添加: #{tag}")
                    except PlaywrightTimeout:
                        print(f"  ⚠️  添加标签失败: {tag}")
                        continue

            # 6. 点击发布按钮
            print("🚀 正在发布...")
            try:
                publish_button = await self.page.wait_for_selector(
                    'button:has-text("发布"), button:has-text("发送")',
                    timeout=5000
                )
                await publish_button.click()

                # 等待发布成功提示
                await self.page.wait_for_selector(
                    'text=发布成功, text=发送成功',
                    timeout=10000
                )
                print("✅ 发布成功！")

                # 等待页面跳转，获取笔记URL
                await asyncio.sleep(3)
                post_url = self.page.url

                return {
                    "status": "success",
                    "post_url": post_url,
                    "images_uploaded": len(images),
                    "error": None
                }

            except PlaywrightTimeout:
                print("❌ 发布失败：超时或未找到发布按钮")
                # 截图用于调试
                await self.screenshot("publish_error.png")
                return {
                    "status": "failed",
                    "error": "Timeout waiting for publish button or success message",
                    "screenshot": "publish_error.png"
                }

        except Exception as e:
            print(f"❌ 发布过程出错: {str(e)}")
            return {
                "status": "failed",
                "error": str(e)
            }


async def test_xiaohongshu_login():
    """测试小红书登录流程"""
    async with XiaohongshuPublisher(headless=False) as publisher:
        # 交互式登录
        success = await publisher.login_interactive()

        if success:
            # 保存session
            await publisher.save_session()
            print("\n✅ 登录测试完成！Session已保存。")
        else:
            print("\n❌ 登录测试失败。")


if __name__ == "__main__":
    # 测试登录
    print("=== 小红书登录测试 ===\n")
    asyncio.run(test_xiaohongshu_login())
