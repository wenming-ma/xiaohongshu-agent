"""Tool orchestration for Xiaohongshu video extraction and transcription."""

from __future__ import annotations

import asyncio
import shutil
import time as _time
from pathlib import Path

import aiohttp
from pydantic_ai import Tool
from pydantic_ai.mcp import MCPServerStdio

from ....config.settings import PathConfig
from ....utils.logger import get_logger
from ..utils.asr import AudioTranscriber
from .extract.agent import ExtractAgent
from .schemas import VideoReadResult

logger = get_logger(__name__)


class XHSVideoExtractTool:
    """Small orchestration tool for extracting and transcribing Xiaohongshu videos."""

    def __init__(self, mcp_server: MCPServerStdio):
        self._extract_agent = ExtractAgent(mcp_server)
        self._transcriber = AudioTranscriber()

    async def extract_xhs_video_url(self, page_url: str = "") -> str:
        result = await self._extract_agent.forward(page_url=page_url)
        return result.model_dump_json(indent=2)

    async def read_video(self, video_url: str = "", page_url: str = "") -> str:
        url = (video_url or "").strip()
        note_url = (page_url or "").strip()
        if not url and not note_url:
            return VideoReadResult(
                error_message="video_url 和 page_url 不能同时为空"
            ).model_dump_json(indent=2)

        tmp_dir = None
        try:
            tmp_dir = PathConfig.DOWNLOADS_DIR / f"xhs_video_{int(_time.time() * 1000)}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            video_path = tmp_dir / "video.mp4"

            if note_url:
                extract_result = await self._extract_agent.forward(page_url=note_url)
                if extract_result.success:
                    url = extract_result.video_url
                    logger.info(
                        "XHSVideoExtractTool: downloading extracted xhs video %s (%s)",
                        url[:80],
                        extract_result.source,
                    )
                    await self._download_video(url, video_path)
                elif url and not url.startswith("blob:"):
                    logger.warning(
                        "XHSVideoExtractTool: xhs extraction failed, fallback to direct url: %s",
                        extract_result.error_message,
                    )
                    await self._download_video(url, video_path)
                else:
                    logger.info(
                        "XHSVideoExtractTool: xhs extraction failed, fallback to page download: %s",
                        extract_result.error_message,
                    )
                    await self._download_from_page(note_url, video_path)
            else:
                logger.info("XHSVideoExtractTool: downloading %s", url[:80])
                await self._download_video(url, video_path)

            logger.info("XHSVideoExtractTool: transcribing %s", video_path.name)
            transcription = await self._transcriber.transcribe(video_path)

            if transcription.success:
                result = VideoReadResult(
                    success=True,
                    transcript=transcription.transcript,
                    language=transcription.language,
                    duration_seconds=transcription.duration_seconds,
                )
            else:
                result = VideoReadResult(error_message=f"转录失败: {transcription.error_message}")
        except Exception as e:
            logger.warning("XHSVideoExtractTool failed: %s", e)
            result = VideoReadResult(error_message=f"{type(e).__name__}: {e}")
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return result.model_dump_json(indent=2)

    @staticmethod
    async def _download_video(url: str, dest: Path) -> None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.xiaohongshu.com/",
        }
        timeout = aiohttp.ClientTimeout(total=120, connect=15)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 64):
                        f.write(chunk)

        if not dest.exists() or dest.stat().st_size < 10_000:
            raise RuntimeError(f"下载的视频文件太小或不存在: {dest.stat().st_size if dest.exists() else 0} bytes")

    @staticmethod
    async def _download_from_page(page_url: str, dest: Path) -> None:
        import yt_dlp

        output_template = str(dest.with_suffix(".%(ext)s"))

        def _sync_download() -> Path:
            ydl_opts = {
                "format": "best[ext=mp4]/best",
                "outtmpl": output_template,
                "quiet": True,
                "no_warnings": True,
                "merge_output_format": "mp4",
                "socket_timeout": 30,
                "retries": 3,
                "referer": "https://www.xiaohongshu.com/",
                "http_headers": {
                    "Referer": "https://www.xiaohongshu.com/",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(page_url, download=True)
                filename = Path(ydl.prepare_filename(info))
                merged = filename.with_suffix(".mp4")
                if merged.exists():
                    return merged
                return filename

        loop = asyncio.get_running_loop()
        downloaded_path = await loop.run_in_executor(None, _sync_download)
        if downloaded_path != dest:
            shutil.move(str(downloaded_path), dest)
        if not dest.exists() or dest.stat().st_size < 10_000:
            raise RuntimeError(
                f"从页面解析下载的视频文件太小或不存在: {dest.stat().st_size if dest.exists() else 0} bytes"
            )

    def get_extract_tool(self) -> Tool:
        return Tool(self.extract_xhs_video_url, takes_ctx=False)

    def get_read_tool(self) -> Tool:
        return Tool(self.read_video, takes_ctx=False)


def create_video_extract_tool(mcp_server: MCPServerStdio) -> XHSVideoExtractTool:
    return XHSVideoExtractTool(mcp_server)
