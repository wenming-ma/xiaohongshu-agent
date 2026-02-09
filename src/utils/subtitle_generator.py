import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# 设置离线模式和禁用警告
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# 添加 CUDA cuBLAS DLL 路径到 PATH
_venv_nvidia_bin = Path(__file__).parent.parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
if _venv_nvidia_bin.exists():
    os.environ["PATH"] = str(_venv_nvidia_bin) + os.pathsep + os.environ.get("PATH", "")

from faster_whisper import WhisperModel
from pydantic_ai import Agent

from ..utils.text_model_selector import get_text_model
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 项目本地缓存路径
PROJECT_CACHE = Path(__file__).parent.parent.parent / ".cache" / "huggingface" / "hub"
LOCAL_WHISPER_MODEL_PATH = PROJECT_CACHE / "models--Systran--faster-whisper-large-v3" / "faster-whisper-large-v3"

SUBTITLE_CONFIG = {
    "WHISPER_MODEL": str(LOCAL_WHISPER_MODEL_PATH),  # 使用本地路径
    "WHISPER_DEVICE": "cuda",
    "WHISPER_COMPUTE_TYPE": "float16",
    "TARGET_LANGUAGE": "zh",
    "FONT_NAME": "Microsoft YaHei",
    "FONT_SIZE": 24,
    "ENABLE_TRANSLATION": True,
}


class SubtitleSegment:
    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text


class SubtitleResult:
    def __init__(
        self,
        success: bool,
        segments: list[SubtitleSegment] = None,
        language: str = "",
        translated: bool = False,
        srt_path: str = "",
        video_with_subs: str = "",
        error_message: str = "",
    ):
        self.success = success
        self.segments = segments or []
        self.language = language
        self.translated = translated
        self.srt_path = srt_path
        self.video_with_subs = video_with_subs
        self.error_message = error_message


class WhisperTranscriber:
    """使用本地 Whisper 模型进行转录（仅文本，用于 ContentAgent）"""

    def __init__(self):
        self.model: Optional[WhisperModel] = None

    def _load_whisper_model(self):
        if self.model is None:
            logger.info(f"加载 Whisper 模型（本地离线模式）...")

            self.model = WhisperModel(
                SUBTITLE_CONFIG["WHISPER_MODEL"],
                device=SUBTITLE_CONFIG["WHISPER_DEVICE"],
                compute_type=SUBTITLE_CONFIG["WHISPER_COMPUTE_TYPE"],
                local_files_only=True,
            )
            logger.info("Whisper 模型加载完成")

    async def transcribe(self, video_path: Path) -> "TranscriptionResult":
        from ..tools.xiaohongshu.video_post.schemas import TranscriptionResult

        if not video_path.exists():
            return TranscriptionResult(success=False, error_message=f"文件不存在: {video_path}")

        try:
            self._load_whisper_model()

            audio_path = await self._extract_audio(video_path)

            logger.info("开始 Whisper 转录（纯文本）...")
            loop = asyncio.get_event_loop()

            def _transcribe():
                segments_iter, info = self.model.transcribe(
                    str(audio_path),
                    language=None,
                    task="transcribe",
                    vad_filter=True,
                )
                segments_list = list(segments_iter)
                transcript = " ".join([seg.text.strip() for seg in segments_list])
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

    async def _extract_audio(self, video_path: Path) -> Path:
        audio_path = Path(tempfile.mktemp(suffix=".mp3"))
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vn", "-acodec", "libmp3lame", "-q:a", "4",
            "-y", str(audio_path),
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


class WhisperSubtitleGenerator:

    def __init__(self):
        self.model: Optional[WhisperModel] = None
        self.translation_agent: Optional[Agent] = None

    def _load_whisper_model(self):
        if self.model is None:
            logger.info(f"加载 Faster-Whisper 模型（本地离线模式，设备: {SUBTITLE_CONFIG['WHISPER_DEVICE']})...")

            self.model = WhisperModel(
                SUBTITLE_CONFIG["WHISPER_MODEL"],
                device=SUBTITLE_CONFIG["WHISPER_DEVICE"],
                compute_type=SUBTITLE_CONFIG["WHISPER_COMPUTE_TYPE"],
                local_files_only=True,
            )
            logger.info("Faster-Whisper 模型加载完成")

    def _init_translation_agent(self):
        if self.translation_agent is None:
            model = get_text_model()
            self.translation_agent = Agent(
                model=model,
                system_prompt="你是专业的字幕翻译专家。将英文字幕翻译成简洁自然的中文，保持口语化风格。",
            )

    async def generate_and_burn(
        self,
        video_path: Path,
        output_path: Path,
        target_language: str = "zh",
    ) -> SubtitleResult:
        try:
            logger.info(f"开始生成字幕: {video_path.name}")

            audio_path = await self._extract_audio(video_path)

            segments, detected_lang = await self._transcribe_with_whisper(audio_path)

            if audio_path.exists():
                audio_path.unlink(missing_ok=True)

            translated = False
            if detected_lang == "en" and target_language == "zh" and SUBTITLE_CONFIG["ENABLE_TRANSLATION"]:
                logger.info("检测到英文，开始翻译成中文...")
                segments = await self._translate_to_chinese(segments)
                translated = True

            srt_path = output_path.with_suffix(".srt")
            self._generate_srt(segments, srt_path)
            logger.info(f"SRT 文件生成: {srt_path}")

            await self._burn_subtitles(video_path, srt_path, output_path)
            logger.info(f"字幕烧录完成: {output_path}")

            return SubtitleResult(
                success=True,
                segments=segments,
                language=detected_lang,
                translated=translated,
                srt_path=str(srt_path),
                video_with_subs=str(output_path),
            )

        except Exception as e:
            logger.error(f"字幕生成失败: {e}")
            return SubtitleResult(
                success=False,
                error_message=str(e),
            )

    async def _extract_audio(self, video_path: Path) -> Path:
        audio_path = Path(tempfile.mktemp(suffix=".mp3"))
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vn", "-acodec", "libmp3lame", "-q:a", "4",
            "-y", str(audio_path),
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

    async def _transcribe_with_whisper(self, audio_path: Path) -> tuple[list[SubtitleSegment], str]:
        self._load_whisper_model()

        logger.info("开始 Faster-Whisper 转录...")
        loop = asyncio.get_event_loop()

        def _transcribe():
            segments_iter, info = self.model.transcribe(
                str(audio_path),
                language=None,
                task="transcribe",
                word_timestamps=True,
                vad_filter=True,
            )
            return list(segments_iter), info

        segments_list, info = await loop.run_in_executor(None, _transcribe)

        detected_lang = info.language
        logger.info(f"检测到语言: {detected_lang}")

        segments = []
        for seg in segments_list:
            segments.append(SubtitleSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
            ))

        logger.info(f"转录完成: {len(segments)} 个字幕片段")
        return segments, detected_lang

    async def _translate_to_chinese(self, segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
        self._init_translation_agent()

        batch_size = 15
        translated_segments = []

        for i in range(0, len(segments), batch_size):
            batch = segments[i:i + batch_size]
            texts = [f"{j+1}. {seg.text}" for j, seg in enumerate(batch)]
            prompt = "将以下英文字幕翻译成中文，保持简洁自然。只输出翻译后的文本，每行一条，格式为 '序号. 翻译内容'：\n\n" + "\n".join(texts)

            result = await self.translation_agent.run(prompt)
            translated_lines = result.data.strip().split("\n")

            for j, seg in enumerate(batch):
                if j < len(translated_lines):
                    translated_text = translated_lines[j]
                    if ". " in translated_text:
                        translated_text = translated_text.split(". ", 1)[1]
                    translated_segments.append(SubtitleSegment(
                        start=seg.start,
                        end=seg.end,
                        text=translated_text.strip(),
                    ))
                else:
                    translated_segments.append(seg)

            logger.info(f"翻译进度: {min(i + batch_size, len(segments))}/{len(segments)}")

        return translated_segments

    def _generate_srt(self, segments: list[SubtitleSegment], output_path: Path) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = self._format_timestamp(seg.start)
                end = self._format_timestamp(seg.end)
                f.write(f"{i}\n{start} --> {end}\n{seg.text}\n\n")

    def _format_timestamp(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    async def _burn_subtitles(self, video_path: Path, srt_path: Path, output_path: Path) -> None:
        srt_path_escaped = str(srt_path).replace("\\", "/").replace(":", r"\:")

        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"subtitles={srt_path_escaped}:force_style='FontName={SUBTITLE_CONFIG['FONT_NAME']},FontSize={SUBTITLE_CONFIG['FONT_SIZE']},PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Shadow=1'",
            "-c:a", "copy",
            "-y", str(output_path),
        ]

        logger.info("开始烧录字幕到视频...")
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
