import asyncio
import subprocess
from pathlib import Path

from ....utils.logger import get_logger

logger = get_logger(__name__)


async def extract_frames(video_path: Path, output_dir: Path, count: int = 3) -> list[Path]:
    """从视频的均匀位置截取关键帧

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录
        count: 截取帧数（默认 3，分别在 25%/50%/75% 位置）

    Returns:
        截取的帧文件路径列表
    """
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    duration = float(stdout.decode().strip())

    frames = []
    # 均匀分布：1/(count+1), 2/(count+1), ..., count/(count+1)
    positions = [duration * (i + 1) / (count + 1) for i in range(count)]

    for i, ts in enumerate(positions):
        frame_path = output_dir / f"frame_{i}.png"
        cmd = [
            "ffmpeg", "-ss", f"{ts:.2f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-y", str(frame_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        await proc.communicate()

        if frame_path.exists() and frame_path.stat().st_size > 0:
            frames.append(frame_path)

    logger.info(f"从视频截取了 {len(frames)} 帧")
    return frames
