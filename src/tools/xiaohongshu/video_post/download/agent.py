import asyncio
import os
from pathlib import Path
from typing import Any, List

import logfire

from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoSource, DownloadResult, Platform
from .....utils.logger import get_logger

logger = get_logger(__name__)

PLATFORM_OPTS = {
    Platform.X: {
        "format": "best[ext=mp4]/best",
        "extra_args": [],
    },
    Platform.INSTAGRAM: {
        "format": "best[ext=mp4]/best",
        "extra_args": ["--cookies-from-browser", "chromium"],
    },
    Platform.FACEBOOK: {
        "format": "best[ext=mp4]/best",
        "extra_args": [],
    },
    Platform.TIKTOK: {
        "format": "best[ext=mp4]/best",
        "extra_args": [],
    },
}

MIN_FILE_SIZE = 100 * 1024  # 100KB
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


class DownloadAgent(BaseAgent):

    role = "视频下载专员"
    goal = "使用 yt-dlp 从多平台下载视频"

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        pass

    async def forward(
        self,
        sources: List[VideoSource],
        output_dir: Path,
    ) -> DownloadResult:
        sorted_sources = sorted(sources, key=lambda s: s.engagement_score, reverse=True)

        logger.info(f"尝试下载 {len(sorted_sources)} 个视频源")

        for i, source in enumerate(sorted_sources):
            logger.info(f"尝试下载 [{i+1}/{len(sorted_sources)}]: {source.platform.value} - {source.url[:60]}")

            result = await self.step(source, output_dir)
            validation = await self.validate(result)

            if validation.passed:
                logger.info(f"下载成功: {result.local_path}")
                return result

            logger.warning(f"下载失败: {result.error_message}")

        raise RuntimeError(f"所有 {len(sorted_sources)} 个视频源下载均失败")

    async def step(self, source: VideoSource, output_dir: Path) -> DownloadResult:
        with logfire.span('video_download:step', platform=source.platform.value, url=source.url[:80]):
            try:
                local_path = await self._download_with_ytdlp(source, output_dir)
                file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

                return DownloadResult(
                    success=True,
                    source=source,
                    local_path=str(local_path),
                    file_size_bytes=file_size,
                    format="mp4",
                )
            except Exception as e:
                logger.error(f"yt-dlp 下载失败: {e}")
                return DownloadResult(
                    success=False,
                    source=source,
                    error_message=str(e),
                )

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, DownloadResult):
            return ValidationResult.failure("输出类型错误")

        if not output.success:
            return ValidationResult.failure(f"下载失败: {output.error_message}")

        path = Path(output.local_path)
        if not path.exists():
            return ValidationResult.failure(f"文件不存在: {output.local_path}")

        if output.file_size_bytes < MIN_FILE_SIZE:
            return ValidationResult.failure(
                f"文件太小 ({output.file_size_bytes} bytes)，可能下载不完整"
            )

        if output.file_size_bytes > MAX_FILE_SIZE:
            return ValidationResult.failure(
                f"文件过大 ({output.file_size_bytes // (1024*1024)} MB)，超过限制"
            )

        suffix = path.suffix.lower()
        if suffix not in ('.mp4', '.webm', '.mkv', '.avi', '.mov'):
            return ValidationResult.failure(f"不支持的视频格式: {suffix}")

        return ValidationResult.success("视频文件验证通过")

    async def _download_with_ytdlp(self, source: VideoSource, output_dir: Path) -> Path:
        import yt_dlp

        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "%(title).50s.%(ext)s")

        platform_opts = PLATFORM_OPTS.get(source.platform, {})
        format_spec = platform_opts.get("format", "best[ext=mp4]/best")

        ydl_opts = {
            "format": format_spec,
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "socket_timeout": 30,
            "retries": 3,
        }

        def _sync_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source.url, download=True)
                filename = ydl.prepare_filename(info)
                base = os.path.splitext(filename)[0]
                for ext in ['.mp4', '.webm', '.mkv']:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        return Path(candidate)
                return Path(filename)

        loop = asyncio.get_event_loop()
        result_path = await loop.run_in_executor(None, _sync_download)
        return result_path
