"""
视频配音执行入口（支持双环境）。

默认策略：
1. 主流程在当前 Python 环境运行；
2. 配音阶段优先切到独立音频环境 `.venv-audio` 执行 `scripts/dub_video.py`；
3. 若显式关闭独立环境，则回退到当前环境内联执行。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DUB_SCRIPT = PROJECT_ROOT / "scripts" / "dub_video.py"


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning(f"{name}={raw!r} 不是有效布尔值，回退默认值 {default}")
    return default


def _get_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} 不是有效数字，回退默认值 {default}")
        return default


def _resolve_dub_script() -> Path:
    configured = os.getenv("VIDEO_DUB_RUNNER_SCRIPT", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path
    return DEFAULT_DUB_SCRIPT


def _resolve_audio_python() -> Path | None:
    configured = os.getenv("VIDEO_DUB_AUDIO_PYTHON", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"VIDEO_DUB_AUDIO_PYTHON 不存在: {path}")

    candidates = [
        PROJECT_ROOT / ".venv-audio" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv-audio" / "bin" / "python",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


async def _run_via_audio_env(
    *,
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    work_dir: Path | None,
    bg_volume: float,
    voice: str = "",
) -> Path:
    dub_script = _resolve_dub_script()
    if not dub_script.exists():
        raise FileNotFoundError(f"配音脚本不存在: {dub_script}")

    audio_python = _resolve_audio_python()
    require_audio_env = _get_env_bool("VIDEO_DUB_REQUIRE_AUDIO_ENV", True)
    if audio_python is None:
        msg = (
            "未找到独立音频环境 Python（预期路径: .venv-audio）。"
            "请先执行: powershell -ExecutionPolicy Bypass -File .\\scripts\\setup_audio_venv.ps1"
        )
        if require_audio_env:
            raise RuntimeError(msg)
        logger.warning(f"{msg}，回退当前环境执行。")
        from .video_dubbing import dub_video

        return await dub_video(
            video_path=video_path,
            srt_path=srt_path,
            output_path=output_path,
            work_dir=work_dir,
            bg_volume=bg_volume,
            voice=voice,
        )

    cmd = [
        str(audio_python),
        str(dub_script),
        "--video",
        str(video_path),
        "--srt",
        str(srt_path),
        "--output",
        str(output_path),
        "--bg-volume",
        f"{bg_volume}",
    ]
    if work_dir is not None:
        cmd.extend(["--work-dir", str(work_dir)])

    logger.info(f"配音使用独立环境: {audio_python}")
    logger.info(f"执行命令: {' '.join(cmd)}")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    if voice:
        env["S2CPP_TTS_VOICE"] = voice
    project_root_str = str(PROJECT_ROOT)
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        if project_root_str not in existing_pythonpath.split(os.pathsep):
            env["PYTHONPATH"] = f"{project_root_str}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = project_root_str

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    timeout_s = _get_env_float("VIDEO_DUB_SUBPROCESS_TIMEOUT_SECONDS", 3600.0)
    try:
        code = await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"配音子进程超时（{timeout_s:.0f}s），已强制终止")
    if code != 0:
        raise RuntimeError(f"独立环境配音失败，退出码={code}")

    if not output_path.exists():
        raise RuntimeError(f"配音流程结束但未生成输出文件: {output_path}")
    return output_path


async def dub_video_with_runner(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    work_dir: Path | None = None,
    bg_volume: float = 0.6,
    voice: str = "",
) -> Path:
    """
    统一配音入口。

    - `VIDEO_DUB_USE_SEPARATE_ENV=1`（默认）: 使用 `.venv-audio` 子进程执行；
    - `VIDEO_DUB_USE_SEPARATE_ENV=0`: 当前环境内联执行。
    """
    use_separate_env = _get_env_bool("VIDEO_DUB_USE_SEPARATE_ENV", True)

    if use_separate_env:
        return await _run_via_audio_env(
            video_path=video_path,
            srt_path=srt_path,
            output_path=output_path,
            work_dir=work_dir,
            bg_volume=bg_volume,
            voice=voice,
        )

    logger.warning("VIDEO_DUB_USE_SEPARATE_ENV=0，配音将使用当前环境执行")
    from .video_dubbing import dub_video

    return await dub_video(
        video_path=video_path,
        srt_path=srt_path,
        output_path=output_path,
        work_dir=work_dir,
        bg_volume=bg_volume,
        voice=voice,
    )
