"""
下载文件管理器
处理 Playwright MCP 下载文件的发现和移动

注意：Playwright 不使用系统 Downloads 目录！
- Playwright 下载到临时目录：%TEMP%/playwright-artifacts-xxx
- Browser Context 关闭时自动删除下载
- 需要通过 --output-dir 参数指定输出目录
"""
import time
import shutil
from pathlib import Path
from typing import Optional
from ..config.settings import TimeoutConfig, PathConfig
from .watermark_remover import remove_gemini_watermark
from .logger import get_logger

logger = get_logger(__name__)


class DownloadManager:
    """Playwright MCP 下载文件管理器"""

    def __init__(self, download_dir: Optional[Path] = None):
        """
        初始化下载管理器

        Args:
            download_dir: 自定义下载目录，默认使用配置
        """
        self.download_dir = download_dir or PathConfig.DOWNLOADS_DIR

    def wait_and_move(
        self,
        target_dir: Path,
        target_name: str,
        file_pattern: str = "*.png",
        timeout: float = None,
        before_time: Optional[float] = None,
        remove_watermark: bool = True
    ) -> Path:
        """
        等待下载完成并移动文件到目标目录

        Args:
            target_dir: 目标目录
            target_name: 目标文件名（不含扩展名）
            file_pattern: 文件匹配模式
            timeout: 超时时间（秒）
            before_time: 只查找此时间之后修改的文件（Unix 时间戳）
            remove_watermark: 是否移除 Gemini 水印（默认 True）

        Returns:
            Path: 移动后的文件路径

        Raises:
            TimeoutError: 等待超时
            FileNotFoundError: 未找到文件
        """
        if timeout is None:
            timeout = TimeoutConfig.DOWNLOAD_TIMEOUT
        if before_time is None:
            before_time = time.time()

        start_time = time.time()
        target_dir.mkdir(parents=True, exist_ok=True)

        while time.time() - start_time < timeout:
            # 查找符合条件的文件
            candidates = []
            for f in self.download_dir.glob(file_pattern):
                # 检查文件修改时间
                if f.stat().st_mtime > before_time:
                    # 检查文件是否完整（不是临时下载文件）
                    if not f.suffix.endswith(('.crdownload', '.tmp', '.part')):
                        candidates.append(f)

            if candidates:
                # 选择最新的文件
                latest = max(candidates, key=lambda p: p.stat().st_mtime)

                # 确定目标路径
                target_path = target_dir / f"{target_name}{latest.suffix}"

                # 移动文件
                shutil.move(str(latest), str(target_path))

                # 移除 Gemini 水印（如果启用且是图片文件）
                if remove_watermark and target_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                    try:
                        remove_gemini_watermark(target_path)
                        logger.info("已移除 Gemini 水印: %s", target_path.name)
                    except Exception as e:
                        logger.warning("去水印失败 (保留原图): %s", e)

                return target_path

            time.sleep(TimeoutConfig.POLL_INTERVAL)

        raise TimeoutError(
            f"等待下载超时 ({timeout}s)，"
            f"下载目录: {self.download_dir}"
        )
