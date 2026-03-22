import asyncio
import os
from pathlib import Path
from typing import Any, List

import logfire

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoSource, DownloadResult, Platform
from ....utils.logger import get_logger
from ....utils.subtitle_generator import WhisperTranscriber, WhisperSubtitleGenerator

logger = get_logger(__name__)

PLATFORM_OPTS = {
    Platform.YOUTUBE: {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "extra_args": [],
    },
    Platform.X: {
        "format": "best[ext=mp4]/best",
        "extra_args": [],
    },
    Platform.INSTAGRAM: {
        "format": "best[ext=mp4]/best",
        "extra_args": ["--cookies-from-browser", "chrome"],
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
DOWNLOAD_TIMEOUT = 600  # 10 minutes


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
                result = await self._transcribe(result)
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

    async def _transcribe(self, result: DownloadResult) -> DownloadResult:
        try:
            transcriber = WhisperTranscriber()
            transcription = await transcriber.transcribe(Path(result.local_path))
            result.transcription = transcription
            if transcription.success:
                logger.info(f"Whisper 转录成功: {len(transcription.transcript)} 字符")
            else:
                logger.warning(f"Whisper 转录失败: {transcription.error_message}")
        except Exception as e:
            logger.warning(f"转录过程异常（不影响下载结果）: {e}")

        try:
            video_path = Path(result.local_path)
            output_dir = video_path.parent
            subtitled_path = output_dir / f"{video_path.stem}_subtitled{video_path.suffix}"

            # 优先使用 yt-dlp 下载的中文字幕（YouTube 等平台）
            ytdlp_srt = self._find_ytdlp_subtitle(video_path)
            if ytdlp_srt:
                logger.info(f"发现 yt-dlp 下载的字幕文件: {ytdlp_srt.name}")
                await self._burn_existing_subtitle(video_path, ytdlp_srt, subtitled_path)

                from ..schemas import SubtitleResult
                result.subtitle = SubtitleResult(
                    success=True,
                    language="zh",
                    translated=True,
                    srt_path=str(ytdlp_srt),
                    video_with_subs=str(subtitled_path),
                )
                result.local_path = str(subtitled_path)
                logger.info(f"使用平台字幕烧录成功: {subtitled_path}")
            else:
                # 回退到 Whisper 转录 + LLM 翻译
                subtitle_gen = WhisperSubtitleGenerator()
                subtitle_result_obj = await subtitle_gen.generate_and_burn(
                    video_path=video_path,
                    output_path=subtitled_path,
                    target_language="zh",
                )

                from ..schemas import SubtitleResult, SubtitleSegment
                result.subtitle = SubtitleResult(
                    success=subtitle_result_obj.success,
                    segments=[
                        SubtitleSegment(start=seg.start, end=seg.end, text=seg.text)
                        for seg in subtitle_result_obj.segments
                    ],
                    language=subtitle_result_obj.language,
                    translated=subtitle_result_obj.translated,
                    srt_path=subtitle_result_obj.srt_path,
                    video_with_subs=subtitle_result_obj.video_with_subs,
                    error_message=subtitle_result_obj.error_message,
                )

                if subtitle_result_obj.success:
                    result.local_path = subtitle_result_obj.video_with_subs
                    logger.info(f"Whisper 字幕生成并烧录成功: {subtitled_path}")
                else:
                    logger.warning(f"字幕生成失败: {subtitle_result_obj.error_message}")

        except Exception as e:
            logger.warning(f"字幕生成过程异常（不影响下载结果）: {e}")

        return result

    def _find_ytdlp_subtitle(self, video_path: Path) -> Path | None:
        """查找 yt-dlp 下载的中文字幕文件（优先中文，其次英文）"""
        base = video_path.stem
        parent = video_path.parent

        # 按优先级查找中文字幕
        for lang in ["zh-Hans", "zh-Hant", "zh"]:
            srt = parent / f"{base}.{lang}.srt"
            if srt.exists():
                return srt
            vtt = parent / f"{base}.{lang}.vtt"
            if vtt.exists():
                return vtt

        return None

    async def _burn_existing_subtitle(self, video_path: Path, srt_path: Path, output_path: Path) -> None:
        """将已有字幕文件烧录到视频中"""
        import subprocess

        srt_path_escaped = str(srt_path).replace("\\", "/").replace(":", r"\:")

        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"subtitles={srt_path_escaped}:force_style='FontName=Microsoft YaHei,FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Shadow=1'",
            "-c:a", "copy",
            "-y", str(output_path),
        ]

        logger.info("烧录平台字幕到视频...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg 字幕烧录失败: {stderr.decode()[-500:]}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("烧录后的视频文件为空")

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

        # YouTube: 尝试下载中文字幕（自动生成或人工上传）
        if source.platform == Platform.YOUTUBE:
            ydl_opts.update({
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["zh-Hans", "zh-Hant", "zh", "en"],
                "subtitlesformat": "srt",
            })

        def _sync_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source.url, download=True)
                filename = ydl.prepare_filename(info)
                base = os.path.splitext(filename)[0]
                for ext in ['.mp4', '.webm', '.mkv', '.avi', '.mov']:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        return Path(candidate)
                return Path(filename)

        loop = asyncio.get_running_loop()
        try:
            result_path = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_download),
                timeout=DOWNLOAD_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"视频下载超时 ({DOWNLOAD_TIMEOUT}s): {source.url[:80]}")
        return result_path
