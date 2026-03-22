"""
Gemini Web UI 图片生成客户端

通过 Playwright 脚本注入自动化 Gemini Web UI 生成图片。
作为 Gemini API 的降级方案，在 API 返回 503 等错误时使用。
"""
import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from ...config.settings import APIConfig, PathConfig, SanitizerConfig, TimeoutConfig
from ..image_sanitizer import sanitize_image
from ..logger import get_logger
from ..watermark_remover import remove_gemini_watermark

logger = get_logger(__name__)

# JS：激活 "Create image" 工具 + 切换 Pro 模式（不含提示词输入）
_ACTIVATE_JS = """
async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // 1. 激活 "Create image" 模式
    let activated = false;
    for (const btn of document.querySelectorAll('button')) {
        if (btn.textContent.includes('Create image') && !btn.textContent.includes('Deselect')) {
            btn.click();
            activated = true;
            break;
        }
    }
    if (!activated) {
        const toolsBtn = document.querySelector('.toolbox-drawer-button')
            || [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Tools');
        if (toolsBtn) {
            toolsBtn.click();
            await sleep(300);
            for (const item of document.querySelectorAll('[role="menuitemcheckbox"]')) {
                if (item.textContent.includes('Create image')) {
                    item.click();
                    activated = true;
                    break;
                }
            }
        }
    }
    if (!activated) throw new Error('CREATE_IMAGE_NOT_FOUND');
    await sleep(500);

    // 2. 验证/切换 Pro 模式
    const modePicker = document.querySelector('[aria-label="Open mode picker"]');
    if (modePicker && !modePicker.textContent.includes('Pro')) {
        modePicker.click();
        await sleep(300);
        for (const mi of document.querySelectorAll('[role="menuitem"]')) {
            if (mi.textContent.includes('Pro')) {
                mi.click();
                break;
            }
        }
        await sleep(500);
    }

    return 'OK';
}
"""

# 轮询检测生成完成的 JS
_POLL_IMAGE_JS = """
() => {
    const imgs = document.querySelectorAll('img');
    for (const img of imgs) {
        if (img.naturalWidth > 200 && img.alt && img.alt.includes('AI generated')) {
            return img.src;
        }
    }
    return null;
}
"""

# 检测登录状态的 JS（Google Account 链接是 <a> 标签，不是 <button>）
_CHECK_LOGIN_JS = """
() => {
    const el = document.querySelector('a[aria-label*="Google Account"], button[aria-label*="Google Account"]');
    return el !== null;
}
"""


class GeminiWebImageClient:
    """Gemini Web UI 图片生成客户端，使用 Playwright 脚本注入，支持多账号轮换"""

    # 类级别轮换索引，所有实例共享
    _current_index: int = 0

    def __init__(self, browser_session_dir: Optional[str] = None):
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._active_session_dir: Optional[str] = None

        base_dir = browser_session_dir or PathConfig.BROWSER_SESSION_GEMINI
        self._session_dirs = self._discover_session_dirs(base_dir)
        logger.info(
            "[GeminiWeb] 发现 %d 个账号会话目录: %s",
            len(self._session_dirs),
            [Path(d).name for d in self._session_dirs],
        )

    @staticmethod
    def _discover_session_dirs(base_dir: str) -> list[str]:
        """扫描 base_dir 下 account* 子目录作为会话列表，无匹配时回退到 base_dir 本身"""
        base = Path(base_dir)
        base.mkdir(parents=True, exist_ok=True)
        subdirs = sorted(
            str(d) for d in base.iterdir()
            if d.is_dir() and d.name.startswith("account")
        )
        return subdirs if subdirs else [str(base)]

    def _pick_session_dir(self) -> str:
        """选取当前轮换到的会话目录"""
        idx = GeminiWebImageClient._current_index % len(self._session_dirs)
        return self._session_dirs[idx]

    def _rotate(self) -> None:
        """轮换到下一个账号"""
        old_idx = GeminiWebImageClient._current_index % len(self._session_dirs)
        GeminiWebImageClient._current_index += 1
        new_idx = GeminiWebImageClient._current_index % len(self._session_dirs)
        logger.info(
            "[GeminiWeb] 账号轮换: %s -> %s",
            Path(self._session_dirs[old_idx]).name,
            Path(self._session_dirs[new_idx]).name,
        )

    async def _ensure_browser(self) -> Page:
        """懒初始化持久化 Chrome 上下文，会话目录变化时重新打开"""
        session_dir = self._pick_session_dir()

        # 会话目录变了，需要关闭旧的
        if self._active_session_dir != session_dir:
            await self.close()

        if self._page and not self._page.is_closed():
            return self._page

        logger.info("[GeminiWeb] 使用会话目录: %s", Path(session_dir).name)
        pw = await async_playwright().start()
        self._context = await pw.chromium.launch_persistent_context(
            user_data_dir=session_dir,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 900},
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._active_session_dir = session_dir
        return self._page

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        image_size: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        max_retries: int = 3,
        reference_images: list[Path] | None = None,
    ) -> Path:
        """
        通过 Gemini Web UI 生成图片

        Args:
            prompt: 图片生成提示词
            output_path: 输出文件路径
            image_size: 未使用（保持与 API 客户端接口一致）
            aspect_ratio: 未使用（保持与 API 客户端接口一致）
            max_retries: 最大重试次数
            reference_images: 参考图片路径列表（通过文件上传传入）

        Returns:
            保存的图片路径
        """
        timeout = TimeoutConfig.GEMINI_WEB_TIMEOUT
        gemini_url = APIConfig.GEMINI_URL

        logger.info("[GeminiWeb] 开始生成图片: %s", output_path.name)
        if reference_images:
            valid_refs = [p for p in reference_images if p.exists()]
            logger.info("[GeminiWeb] 附加 %d 张参考图片", len(valid_refs))
        else:
            valid_refs = []
        logger.debug("[GeminiWeb] 提示词: %s...", prompt[:100])

        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                page = await self._ensure_browser()

                # 1. 导航到 Gemini（每次新聊天，避免上下文污染）
                await page.goto(gemini_url, wait_until="domcontentloaded", timeout=30000)

                # 2. 等待页面加载（等待编辑器 + 额外等待确保快捷按钮渲染）
                await page.wait_for_selector(
                    '[aria-label="Enter a prompt for Gemini"]',
                    timeout=15000,
                )
                await asyncio.sleep(2)

                # 3. 检查登录状态
                is_logged_in = await page.evaluate(_CHECK_LOGIN_JS)
                if not is_logged_in:
                    raise RuntimeError(
                        "Gemini Web 未登录。请手动在浏览器中登录 Google 账号后重试。"
                        f"\n会话目录: {self._active_session_dir}"
                    )

                # 4a. 激活 "Create image" + Pro 模式
                result = await page.evaluate(_ACTIVATE_JS)
                if result != "OK":
                    raise RuntimeError(f"工具激活失败: {result}")

                # 4b. 上传参考图片（激活 Create image 后上传，避免模式切换清除附件）
                if valid_refs:
                    await self._upload_reference_images(page, valid_refs)

                # 4c. 输入提示词到编辑器
                editor = page.locator('[aria-label="Enter a prompt for Gemini"]')
                await editor.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Delete")

                # 尝试剪贴板粘贴（需要窗口焦点，可能失败）
                await page.evaluate("(text) => navigator.clipboard.writeText(text)", prompt)
                await page.keyboard.press("Control+V")
                await asyncio.sleep(1)

                # 验证文本是否已输入，未输入则用 insertText 降级
                has_text = await page.evaluate("""
                    () => {
                        const el = document.querySelector('[aria-label="Enter a prompt for Gemini"]');
                        return el && el.textContent.trim().length > 0;
                    }
                """)
                if not has_text:
                    logger.warning("[GeminiWeb] 剪贴板粘贴未生效，改用 insertText 输入")
                    await editor.click()
                    await page.keyboard.insert_text(prompt)
                    await asyncio.sleep(0.5)

                # 4d. 等待发送按钮可用后点击
                send_btn = page.locator('[aria-label="Send message"]')
                try:
                    await send_btn.click(timeout=10000)
                except Exception:
                    # 发送按钮仍不可用，尝试 Enter 发送
                    logger.warning("[GeminiWeb] 发送按钮不可用，尝试按 Enter 发送")
                    await editor.focus()
                    await page.keyboard.press("Enter")

                logger.info("[GeminiWeb] 提示词已发送，等待图片生成...")

                # 5. 轮询等待图片生成完成
                image_url = await self._poll_for_image(page, timeout)

                # 6. 下载图片（通过浏览器上下文，携带认证 cookies）
                image_url = self._optimize_image_url(image_url)
                image_data = await self._download_image_via_browser(page, image_url)

                # 7. 保存图片
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_data)
                logger.info("[GeminiWeb] 图片已保存: %s (%d KB)", output_path, len(image_data) // 1024)

                # 8. 后处理：去水印 + 反 AI 检测
                try:
                    remove_gemini_watermark(output_path)
                    logger.debug("[GeminiWeb] 可见水印已去除: %s", output_path.name)
                except Exception as e:
                    logger.warning("[GeminiWeb] 去可见水印失败，继续处理: %s", e)

                if SanitizerConfig.ENABLED:
                    try:
                        output_path = await sanitize_image(output_path)
                    except Exception as e:
                        logger.warning("[GeminiWeb] 图片后处理失败，使用原始文件: %s", e)

                # 成功后关闭浏览器并轮换到下一个账号
                await self.close()
                self._rotate()

                return output_path

            except Exception as e:
                last_error = e
                logger.warning(
                    "[GeminiWeb] 图片生成失败 (%d/%d): %s",
                    attempt + 1, max_retries, str(e),
                )
                if attempt < max_retries - 1:
                    delay = min(5 * (attempt + 1), 30)
                    logger.info("[GeminiWeb] 等待 %d 秒后重试...", delay)
                    await asyncio.sleep(delay)

        raise last_error or Exception("[GeminiWeb] 图片生成失败，已达最大重试次数")

    async def _upload_reference_images(self, page: Page, image_paths: list[Path]) -> None:
        """通过 Gemini Web UI 的文件上传功能上传参考图片"""
        for i, img_path in enumerate(image_paths):
            logger.info("[GeminiWeb] 上传参考图片 %d/%d: %s", i + 1, len(image_paths), img_path.name)

            # 点击编辑器激活上传按钮
            editor = page.locator('[aria-label="Enter a prompt for Gemini"]')
            await editor.click()
            await asyncio.sleep(0.5)

            # 点击上传菜单按钮（可能是 Open 或 Close 状态）
            open_btn = page.locator('[aria-label="Open upload file menu"]')
            if await open_btn.count():
                await open_btn.click()
                await asyncio.sleep(0.5)

            # 通过 filechooser 上传文件
            upload_item = page.locator('[data-test-id="local-images-files-uploader-button"]')
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                await upload_item.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(img_path))

            # 等待上传完成（Loading image 消失）
            loading = page.locator('text=Loading image')
            if await loading.count():
                try:
                    await loading.wait_for(state="hidden", timeout=30000)
                except Exception:
                    logger.warning("[GeminiWeb] 等待图片上传超时，继续执行")
            await asyncio.sleep(1)
            logger.debug("[GeminiWeb] 参考图片 %d 上传完成", i + 1)

        logger.info("[GeminiWeb] %d 张参考图片上传完成", len(image_paths))

    async def _poll_for_image(self, page: Page, timeout: int) -> str:
        """轮询页面直到图片生成完成"""
        poll_interval = 2
        elapsed = 0

        while elapsed < timeout:
            image_url = await page.evaluate(_POLL_IMAGE_JS)
            if image_url:
                logger.info("[GeminiWeb] 图片生成完成 (耗时 %ds)", elapsed)
                return image_url
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"[GeminiWeb] 图片生成超时 ({timeout}s)")

    @staticmethod
    def _optimize_image_url(url: str) -> str:
        """优化图片 URL 获取更高分辨率"""
        # lh3.googleusercontent.com URL 可通过修改后缀获取更高分辨率
        if "=s1024" in url:
            url = url.replace("=s1024", "=s2048")
        elif url.endswith("-rj"):
            url = url.rsplit("=", 1)[0] + "=s2048"
        return url

    async def _download_image_via_browser(self, page: Page, url: str, max_retries: int = 3) -> bytes:
        """通过 Playwright API 请求上下文下载图片（携带浏览器 cookies）"""
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                # 使用 Playwright 的 request context（自动携带浏览器 cookies）
                resp = await page.context.request.get(url)
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")
                data = await resp.body()
                if len(data) < 1024:
                    raise ValueError(f"图片数据过小: {len(data)} bytes")
                return data
            except Exception as e:
                last_error = e
                logger.warning("[GeminiWeb] 图片下载失败 (%d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)

        raise last_error or Exception("[GeminiWeb] 图片下载失败")

    async def close(self):
        """清理浏览器资源"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
