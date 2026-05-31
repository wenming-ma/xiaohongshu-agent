"""
Gemini Web UI 图片生成客户端

通过 Playwright 脚本注入自动化 Gemini Web UI 生成图片。
作为 Gemini API 的降级方案，在 API 返回 503 等错误时使用。
"""
import asyncio
import mimetypes
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from playwright.async_api import (
    BrowserContext,
    Download,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from ...config.settings import APIConfig, PathConfig, TimeoutConfig
from ..logger import get_logger

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

# 发送前记录页面上已有图片的 src，避免把参考图/历史图误判成新结果
_SNAPSHOT_IMAGE_SOURCES_JS = """
() => Array.from(
    new Set(
        Array.from(document.images)
            .map(img => img.currentSrc || img.src || '')
            .filter(Boolean)
    )
)
"""

# 轮询检测生成完成的 JS
_POLL_IMAGE_JS = """
({ excludedSources = [] } = {}) => {
    const isVisible = (img) => {
        const rect = img.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    const excluded = new Set(excludedSources);
    const candidates = [];
    for (const [index, img] of Array.from(document.images).entries()) {
        const src = img.currentSrc || img.src || '';
        if (excluded.has(src)) continue;
        if (!src || img.naturalWidth < 200 || img.naturalHeight < 200) continue;
        const rect = img.getBoundingClientRect();
        const score =
            (isVisible(img) ? 1_000_000 : 0) +
            ((img.alt || '').includes('AI generated') ? 500_000 : 0) +
            Math.round(rect.width * rect.height) +
            index;
        candidates.push({
            index,
            score,
            src,
            width: img.naturalWidth,
            height: img.naturalHeight,
            alt: img.alt || '',
        });
    }
    if (!candidates.length) return null;
    candidates.sort((a, b) => a.score - b.score);
    return candidates[candidates.length - 1];
}
"""

_CLICK_NATIVE_DOWNLOAD_JS = """
async (sourceUrl) => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const normalize = value => (value || '').trim().toLowerCase();
    const labelOf = el => normalize(
        el?.getAttribute?.('aria-label')
        || el?.getAttribute?.('title')
        || el?.getAttribute?.('download')
        || el?.textContent
        || ''
    );
    const controlSelector = 'a[download], button, a, [role="button"], [role="menuitem"], [role="menuitemcheckbox"]';
    const images = Array.from(document.images).filter(img => img.naturalWidth > 200 && img.naturalHeight > 200);
    const target =
        images.find(img => (img.currentSrc || img.src || '') === sourceUrl)
        || images[images.length - 1]
        || null;

    const anchorCandidates = [];
    const scopes = [
        target?.closest('figure'),
        target?.closest('[role="listitem"]'),
        target?.closest('[data-turn-id]'),
        target?.parentElement,
        document,
    ].filter(Boolean);

    for (const scope of scopes) {
        for (const anchor of Array.from(scope.querySelectorAll('a[download]'))) {
            if (!anchorCandidates.includes(anchor)) {
                anchorCandidates.push(anchor);
            }
        }
    }

    const exactAnchor = anchorCandidates.find(anchor => {
        const href = anchor.getAttribute('href') || anchor.href || '';
        return href === sourceUrl;
    });
    if (exactAnchor) {
        exactAnchor.click();
        return {
            ok: true,
            strategy: 'native-anchor-exact',
            filename: exactAnchor.getAttribute('download') || null,
        };
    }

    const fallbackAnchor = anchorCandidates[anchorCandidates.length - 1];
    if (fallbackAnchor) {
        fallbackAnchor.click();
        return {
            ok: true,
            strategy: 'native-anchor',
            filename: fallbackAnchor.getAttribute('download') || null,
        };
    }

    const controls = Array.from(document.querySelectorAll(controlSelector));
    const downloadControl = controls.find(el => {
        const label = labelOf(el);
        return (
            (label.includes('download') && !label.includes('downloading'))
            || label.includes('save image')
            || label.includes('download image')
        );
    });

    if (downloadControl) {
        downloadControl.click();
        await sleep(400);

        const fullSizeControl = Array.from(document.querySelectorAll(controlSelector)).find(el => {
            const label = labelOf(el);
            return (
                label.includes('full size')
                || label.includes('original')
                || label.includes('download full size')
            );
        });
        if (fullSizeControl) {
            fullSizeControl.click();
            return { ok: true, strategy: 'download-menu-full-size' };
        }

        const menuAnchor = Array.from(document.querySelectorAll('a[download]')).pop();
        if (menuAnchor) {
            menuAnchor.click();
            return {
                ok: true,
                strategy: 'download-menu-anchor',
                filename: menuAnchor.getAttribute('download') || null,
            };
        }

        return { ok: true, strategy: 'download-control' };
    }

    return { ok: false, error: 'native download control not found' };
}
"""

_TRIGGER_OBJECT_URL_DOWNLOAD_JS = """
async ({ sourceUrl, suggestedName }) => {
    const link = document.createElement('a');
    link.href = sourceUrl;
    link.download = suggestedName || 'cover';
    link.rel = 'noopener';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    await new Promise(resolve => setTimeout(resolve, 100));
    link.remove();
    return { ok: true, strategy: 'synthetic-anchor' };
}
"""

_MIN_IMAGE_BYTES = 1024
_KNOWN_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

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
        self._pw = None  # Playwright 实例，必须存储以便正确清理
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

        # 确保旧资源完全清理（处理 page 已关闭但 pw/context 仍在的情况）
        await self.close()

        # 清理残留的 Chrome profile 锁文件（崩溃恢复）
        self._cleanup_profile_locks(session_dir)

        logger.info("[GeminiWeb] 使用会话目录: %s", Path(session_dir).name)
        self._pw = await async_playwright().start()
        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=session_dir,
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1280, "height": 900},
            )
        except Exception:
            # 浏览器启动失败，清理 Playwright 实例防止泄漏
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
            raise
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
        reference_images: list[tuple[str, Path] | Path] | None = None,
    ) -> Path:
        """
        通过 Gemini Web UI 生成图片

        Args:
            prompt: 图片生成提示词
            output_path: 输出文件路径
            image_size: 未使用（保持与 API 客户端接口一致）
            aspect_ratio: 未使用（保持与 API 客户端接口一致）
            max_retries: 最大重试次数
            reference_images: 参考图片列表，支持 [(item_name, path), ...] 或 [path, ...]

        Returns:
            保存的图片路径
        """
        timeout = TimeoutConfig.GEMINI_WEB_TIMEOUT
        gemini_url = APIConfig.GEMINI_URL

        logger.info("[GeminiWeb] 开始生成图片: %s", output_path.name)
        if reference_images:
            valid_refs = [
                item[1] if isinstance(item, tuple) else item
                for item in reference_images
            ]
            valid_refs = [p for p in valid_refs if p.exists()]
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

                # 2. 等待页面加载（编辑器 + 网络空闲）
                await page.wait_for_selector(
                    '[aria-label="Enter a prompt for Gemini"]',
                    timeout=30000,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    logger.debug("[GeminiWeb] networkidle 超时，继续后续流程")

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

                existing_image_sources = await self._snapshot_existing_image_sources(page)

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
                image_meta = await self._poll_for_image(
                    page,
                    timeout,
                    excluded_sources=existing_image_sources,
                )

                # 6. 下载图片（优先走浏览器原生下载事件）
                output_path = await self._download_generated_image(page, image_meta, output_path)
                logger.info(
                    "[GeminiWeb] 图片已保存: %s (%d KB)",
                    output_path,
                    output_path.stat().st_size // 1024,
                )

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
                # 清理浏览器资源，确保下次重试从干净状态开始
                await self.close()
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

            # 等待上传按钮出现（网络慢时可能延迟渲染）
            open_btn = page.locator('[aria-label="Open upload file menu"]')
            try:
                await open_btn.wait_for(state="visible", timeout=5000)
                await open_btn.click()
            except Exception:
                pass  # 菜单可能已展开

            # 等待 Upload files 按钮出现
            upload_item = page.locator('[data-test-id="local-images-files-uploader-button"]')
            await upload_item.wait_for(state="visible", timeout=5000)

            # 通过 filechooser 上传文件
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                await upload_item.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(img_path))

            # 等待上传完成：先等 "Loading image" 出现，再等它消失
            loading = page.locator('text=Loading image')
            try:
                await loading.wait_for(state="visible", timeout=5000)
                await loading.wait_for(state="hidden", timeout=60000)
            except Exception:
                # Loading 可能太快闪过，或超时 — 改用 Image preview 确认
                logger.debug("[GeminiWeb] Loading 状态未捕获，等待预览图出现")
                try:
                    await page.locator('button:has-text("Remove file")').last.wait_for(
                        state="visible", timeout=30000
                    )
                except Exception:
                    logger.warning("[GeminiWeb] 等待图片上传确认超时，继续执行")

            logger.debug("[GeminiWeb] 参考图片 %d 上传完成", i + 1)

        logger.info("[GeminiWeb] %d 张参考图片上传完成", len(image_paths))

    async def _snapshot_existing_image_sources(self, page: Page) -> set[str]:
        """记录发送前页面上已有的图片 src，避免误选参考图或历史图。"""
        sources = await page.evaluate(_SNAPSHOT_IMAGE_SOURCES_JS)
        if not isinstance(sources, list):
            return set()
        return {str(src).strip() for src in sources if src is not None and str(src).strip()}

    async def _poll_for_image(
        self,
        page: Page,
        timeout: int,
        *,
        excluded_sources: set[str] | None = None,
    ) -> dict[str, Any]:
        """轮询页面直到图片生成完成"""
        poll_interval = 2
        elapsed = 0
        excluded_payload = {"excludedSources": sorted(excluded_sources or set())}

        while elapsed < timeout:
            image_meta = await page.evaluate(_POLL_IMAGE_JS, excluded_payload)
            if image_meta and image_meta.get("src"):
                logger.info(
                    "[GeminiWeb] 图片生成完成 (耗时 %ds, src=%s)",
                    elapsed,
                    str(image_meta["src"])[:120],
                )
                return image_meta
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

    async def _download_generated_image(
        self,
        page: Page,
        image_meta: dict[str, Any],
        output_path: Path,
    ) -> Path:
        source_url = str(image_meta.get("src") or "").strip()
        if not source_url:
            raise ValueError("[GeminiWeb] 图片候选缺少 src")

        try:
            return await self._download_via_native_control(page, source_url, output_path)
        except Exception as exc:
            logger.warning("[GeminiWeb] 原生下载控件失败，准备回退: %s", exc)

        if source_url.startswith(("blob:", "data:")):
            return await self._download_via_object_url(page, source_url, output_path)

        optimized_url = self._optimize_image_url(source_url)
        return await self._download_via_request(page, optimized_url, output_path)

    async def _download_via_native_control(self, page: Page, source_url: str, output_path: Path) -> Path:
        click_result: dict[str, Any] = {}
        try:
            async with page.expect_download(timeout=10000) as download_info:
                click_result = await page.evaluate(_CLICK_NATIVE_DOWNLOAD_JS, source_url)
            download = await download_info.value
        except PlaywrightTimeoutError as exc:
            detail = click_result.get("error") if isinstance(click_result, dict) else None
            raise ValueError(detail or "未触发下载事件") from exc

        if not click_result.get("ok"):
            raise ValueError(click_result.get("error") or "下载控件不可用")

        return await self._save_download(
            download,
            output_path,
            strategy=str(click_result.get("strategy") or "native-download"),
        )

    async def _download_via_object_url(self, page: Page, source_url: str, output_path: Path) -> Path:
        trigger_result: dict[str, Any] = {}
        payload = {
            "sourceUrl": source_url,
            "suggestedName": output_path.name,
        }
        try:
            async with page.expect_download(timeout=10000) as download_info:
                trigger_result = await page.evaluate(_TRIGGER_OBJECT_URL_DOWNLOAD_JS, payload)
            download = await download_info.value
        except PlaywrightTimeoutError as exc:
            detail = trigger_result.get("error") if isinstance(trigger_result, dict) else None
            raise ValueError(detail or "对象 URL 未触发下载事件") from exc

        if not trigger_result.get("ok"):
            raise ValueError(trigger_result.get("error") or "对象 URL 下载失败")

        return await self._save_download(
            download,
            output_path,
            strategy=str(trigger_result.get("strategy") or "object-url"),
        )

    async def _download_via_request(self, page: Page, url: str, output_path: Path) -> Path:
        resp = await page.context.request.get(url)
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        data = await resp.body()
        if len(data) < _MIN_IMAGE_BYTES:
            raise ValueError(f"图片数据过小: {len(data)} bytes")

        target_path = self._resolve_output_path(
            output_path,
            suggested_filename=Path(urlsplit(url).path).name or output_path.name,
            content_type=resp.headers.get("content-type"),
            data=data,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        validated_path = self._normalize_and_validate_image_file(target_path)
        logger.info(
            "[GeminiWeb] request 下载完成: %s (%d KB)",
            validated_path.name,
            validated_path.stat().st_size // 1024,
        )
        return validated_path

    async def _save_download(self, download: Download, output_path: Path, strategy: str) -> Path:
        target_path = self._resolve_output_path(
            output_path,
            suggested_filename=download.suggested_filename,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(target_path)
        validated_path = self._normalize_and_validate_image_file(target_path)
        logger.info(
            "[GeminiWeb] %s 下载完成: %s (%d KB)",
            strategy,
            validated_path.name,
            validated_path.stat().st_size // 1024,
        )
        return validated_path

    def _resolve_output_path(
        self,
        output_path: Path,
        suggested_filename: str | None = None,
        content_type: str | None = None,
        data: bytes | None = None,
    ) -> Path:
        suffix = ""
        if suggested_filename:
            suffix = Path(suggested_filename).suffix.lower()
        if not suffix and content_type:
            guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
            suffix = (guessed or "").lower()
        if not suffix and data:
            suffix = self._sniff_image_suffix(data) or ""
        if suffix not in _KNOWN_IMAGE_SUFFIXES:
            suffix = output_path.suffix.lower()
        if suffix in _KNOWN_IMAGE_SUFFIXES:
            return output_path.with_suffix(".jpg" if suffix == ".jpeg" else suffix)
        return output_path

    def _normalize_and_validate_image_file(self, path: Path) -> Path:
        data = path.read_bytes()
        if len(data) < _MIN_IMAGE_BYTES:
            raise ValueError(f"图片数据过小: {len(data)} bytes")

        detected_suffix = self._sniff_image_suffix(data)
        if detected_suffix:
            normalized_suffix = ".jpg" if detected_suffix == ".jpeg" else detected_suffix
            current_suffix = ".jpg" if path.suffix.lower() == ".jpeg" else path.suffix.lower()
            if current_suffix != normalized_suffix:
                new_path = path.with_suffix(normalized_suffix)
                path.replace(new_path)
                path = new_path
        elif path.suffix.lower() not in _KNOWN_IMAGE_SUFFIXES:
            raise ValueError(f"无法识别图片格式: {path.name}")

        return path

    @staticmethod
    def _sniff_image_suffix(data: bytes) -> str | None:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return ".webp"
        return None

    @staticmethod
    def _cleanup_profile_locks(user_data_dir: str):
        """清理残留的 Chrome profile 锁文件（处理前次崩溃遗留）"""
        for lock_name in ("lockfile", "SingletonLock"):
            lock_path = Path(user_data_dir) / lock_name
            try:
                if lock_path.exists():
                    lock_path.unlink()
                    logger.info("[GeminiWeb] 清理残留锁文件: %s", lock_name)
            except OSError:
                pass  # 文件仍被运行中的进程锁定，跳过

    async def close(self):
        """清理浏览器资源（包括 Playwright 实例）"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
