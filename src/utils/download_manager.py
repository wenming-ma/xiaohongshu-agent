"""
下载文件管理器
处理浏览器下载文件的发现和移动
"""
import time
import shutil
from pathlib import Path
from typing import Optional


class DownloadManager:
    """浏览器下载文件管理器"""

    # 默认下载目录（Windows）
    DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"

    # 等待下载的超时时间（秒）
    DOWNLOAD_TIMEOUT = 60

    # 轮询间隔（秒）
    POLL_INTERVAL = 2

    def __init__(self, download_dir: Optional[Path] = None):
        """
        初始化下载管理器

        Args:
            download_dir: 自定义下载目录，默认为系统下载目录
        """
        self.download_dir = download_dir or self.DEFAULT_DOWNLOAD_DIR

    def wait_and_move(
        self,
        target_dir: Path,
        target_name: str,
        file_pattern: str = "*.png",
        timeout: float = DOWNLOAD_TIMEOUT,
        before_time: Optional[float] = None
    ) -> Path:
        """
        等待下载完成并移动文件到目标目录

        Args:
            target_dir: 目标目录
            target_name: 目标文件名（不含扩展名）
            file_pattern: 文件匹配模式
            timeout: 超时时间（秒）
            before_time: 只查找此时间之后修改的文件（Unix 时间戳）

        Returns:
            Path: 移动后的文件路径

        Raises:
            TimeoutError: 等待超时
            FileNotFoundError: 未找到文件
        """
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

                return target_path

            time.sleep(self.POLL_INTERVAL)

        raise TimeoutError(
            f"等待下载超时 ({timeout}s)，"
            f"下载目录: {self.download_dir}"
        )
