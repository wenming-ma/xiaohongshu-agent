from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


async def has_audio_track(video_path: Path) -> bool:
    probe = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(video_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _ = await probe.communicate()
    return bool(stdout.strip())


async def extract_audio_track(video_path: Path) -> Path:
    if not await has_audio_track(video_path):
        raise RuntimeError("视频无音频轨道，无法提取音频")

    audio_path = Path(tempfile.mktemp(suffix=".mp3"))
    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "4",
        "-y",
        str(audio_path),
    ]
    logger.info("提取音频: %s -> %s", video_path.name, audio_path.name)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg 音频提取失败: {stderr.decode()[-500:]}")
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("ffmpeg 输出文件为空")

    logger.info("音频提取完成: %.1f MB", audio_path.stat().st_size / (1024 * 1024))
    return audio_path
