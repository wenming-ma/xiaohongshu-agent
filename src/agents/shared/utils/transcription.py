import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from threading import Lock
from typing import Optional

from faster_whisper import WhisperModel

from ....utils.logger import get_logger

# 设置离线模式和禁用警告
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# 添加 CUDA cuBLAS DLL 路径到 PATH
_venv_nvidia_bin = Path(__file__).parent.parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
if _venv_nvidia_bin.exists():
    os.environ["PATH"] = str(_venv_nvidia_bin) + os.pathsep + os.environ.get("PATH", "")

logger = get_logger(__name__)

PROJECT_CACHE = Path(__file__).parent.parent.parent / ".cache" / "huggingface" / "hub"
LOCAL_TRANSCRIPTION_MODEL_PATH = PROJECT_CACHE / "models--Systran--faster-whisper-large-v3" / "faster-whisper-large-v3"

TRANSCRIPTION_CONFIG = {
    "MODEL_PATH": str(LOCAL_TRANSCRIPTION_MODEL_PATH),
    "DEVICE": "cuda",
    "COMPUTE_TYPE": "float16",
}

_shared_transcription_model: Optional[WhisperModel] = None
_shared_transcription_model_lock = Lock()


def get_transcription_model() -> WhisperModel:
    global _shared_transcription_model
    if _shared_transcription_model is not None:
        return _shared_transcription_model

    with _shared_transcription_model_lock:
        if _shared_transcription_model is None:
            logger.info("加载音频转录模型（本地离线模式）...")
            _shared_transcription_model = WhisperModel(
                TRANSCRIPTION_CONFIG["MODEL_PATH"],
                device=TRANSCRIPTION_CONFIG["DEVICE"],
                compute_type=TRANSCRIPTION_CONFIG["COMPUTE_TYPE"],
                local_files_only=True,
            )
            logger.info("音频转录模型加载完成")
    return _shared_transcription_model


def release_transcription_model() -> None:
    import gc

    global _shared_transcription_model
    with _shared_transcription_model_lock:
        if _shared_transcription_model is not None:
            del _shared_transcription_model
            _shared_transcription_model = None
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass


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
    logger.info(f"提取音频: {video_path.name} -> {audio_path.name}")

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

    logger.info(f"音频提取完成: {audio_path.stat().st_size / (1024 * 1024):.1f} MB")
    return audio_path


class AudioTranscriber:
    """使用本地转录模型进行纯文本转录。"""

    def _load_model(self) -> None:
        self.model = get_transcription_model()

    async def transcribe(self, video_path: Path) -> "TranscriptionResult":
        from ...video_post.schemas import TranscriptionResult

        if not video_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {video_path}")

        try:
            self._load_model()
            audio_path = await extract_audio_track(video_path)

            logger.info("开始音频转录（纯文本）...")
            loop = asyncio.get_event_loop()

            def _transcribe():
                segments_iter, info = self.model.transcribe(
                    str(audio_path),
                    language=None,
                    task="transcribe",
                    vad_filter=True,
                )
                segments_list = list(segments_iter)
                transcript = " ".join(seg.text.strip() for seg in segments_list)
                return transcript, info.language

            transcript, detected_lang = await loop.run_in_executor(None, _transcribe)

            if audio_path.exists():
                audio_path.unlink(missing_ok=True)

            logger.info(f"转录完成: {len(transcript)} 字符，语言: {detected_lang}")
            return TranscriptionResult(
                success=True,
                transcript=transcript,
                language=detected_lang,
            )
        except Exception as e:
            logger.error(f"转录失败: {e}")
            return TranscriptionResult(success=False, error_message=str(e))
