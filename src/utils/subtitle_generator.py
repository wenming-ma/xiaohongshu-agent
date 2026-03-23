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

from ..utils.providers import get_text_model
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
    "FONT_SIZE": 28,
    "ENABLE_TRANSLATION": True,
}

# ASS 颜色格式: &H00BBGGRR（注意 BGR 顺序）
SUBTITLE_STYLES = {
    "food": {  # 美食/烹饪 → 暖黄色
        "PrimaryColour": "&H0000FFFF",   # 亮黄 #FFFF00
        "OutlineColour": "&H00000000",   # 黑色描边
    },
    "fashion": {  # 穿搭/美妆 → 粉色
        "PrimaryColour": "&H00B469FF",   # 粉色 #FF69B4
        "OutlineColour": "&H00FFFFFF",   # 白色描边
    },
    "travel": {  # 旅行/生活 → 天蓝
        "PrimaryColour": "&H00FFBF00",   # 天蓝 #00BFFF
        "OutlineColour": "&H00FFFFFF",   # 白色描边
    },
    "tech": {  # 科技/数码 → 青色
        "PrimaryColour": "&H00FFFF00",   # 青色 #00FFFF
        "OutlineColour": "&H00000000",   # 黑色描边
    },
    "fitness": {  # 运动/健身 → 活力绿
        "PrimaryColour": "&H0000FF7F",   # 春绿 #7FFF00
        "OutlineColour": "&H00000000",   # 黑色描边
    },
    "default": {  # 默认 → 白色
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
    },
}

# 话题关键词 → 配色方案映射
_STYLE_KEYWORDS = {
    "food": [
        "美食", "烹饪", "做饭", "食谱", "料理", "便当", "甜点", "烘焙", "厨房", "菜",
        "food", "cook", "recipe", "bento", "kitchen", "bake", "meal", "dish", "ramen",
        "sushi", "dessert", "lunch", "dinner", "breakfast",
    ],
    "fashion": [
        "穿搭", "时尚", "美妆", "化妆", "护肤", "搭配", "衣服", "口红", "妆容",
        "fashion", "makeup", "beauty", "skincare", "outfit", "style", "cosmetic",
    ],
    "travel": [
        "旅行", "旅游", "攻略", "打卡", "探店", "城市", "酒店", "风景", "游",
        "travel", "trip", "tour", "vlog", "explore", "city", "hotel", "景",
    ],
    "tech": [
        "科技", "数码", "手机", "电脑", "测评", "开箱", "编程", "AI",
        "tech", "review", "unbox", "phone", "computer", "gadget", "code",
    ],
    "fitness": [
        "健身", "运动", "减肥", "瑜伽", "跑步", "训练", "塑形",
        "fitness", "workout", "gym", "yoga", "exercise", "training",
    ],
}


def pick_subtitle_style(topic: str) -> dict:
    """根据话题关键词选择字幕配色方案"""
    topic_lower = topic.lower()
    for style_name, keywords in _STYLE_KEYWORDS.items():
        if any(kw in topic_lower for kw in keywords):
            logger.info(f"字幕配色: {style_name}")
            return SUBTITLE_STYLES[style_name]
    logger.info("字幕配色: default")
    return SUBTITLE_STYLES["default"]


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
        from ..agents.video_post.schemas import TranscriptionResult

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
                system_prompt="你是小红书风格的字幕翻译专家。翻译风格要求：口语化、轻松活泼，像年轻人日常聊天；适当使用 emoji 增加趣味感（不要过度）；保留语气词和情感表达；翻译要简短精练，适合视频字幕阅读。支持英语、日语、韩语、法语、西班牙语等所有语言到中文的翻译。",
            )

    async def generate_and_burn(
        self,
        video_path: Path,
        output_path: Path,
        target_language: str = "zh",
        topic: str = "",
        font_file: str = "",
    ) -> SubtitleResult:
        try:
            logger.info(f"开始生成字幕: {video_path.name}")

            audio_path = await self._extract_audio(video_path)

            segments, detected_lang = await self._transcribe_with_whisper(audio_path)

            if audio_path.exists():
                audio_path.unlink(missing_ok=True)

            translated = False
            if detected_lang != "zh" and target_language == "zh" and SUBTITLE_CONFIG["ENABLE_TRANSLATION"]:
                logger.info(f"检测到 {detected_lang}，开始翻译成中文...")
                segments = await self._translate_to_chinese(segments, source_language=detected_lang)
                translated = True

            srt_path = output_path.with_suffix(".srt")
            self._generate_srt(segments, srt_path)
            logger.info(f"SRT 文件生成: {srt_path}")

            await self._burn_subtitles(video_path, srt_path, output_path, topic=topic, font_file=font_file)
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

    async def _translate_to_chinese(self, segments: list[SubtitleSegment], source_language: str = "en") -> list[SubtitleSegment]:
        self._init_translation_agent()

        LANG_NAMES = {
            "en": "英文", "ja": "日文", "ko": "韩文", "fr": "法文",
            "es": "西班牙文", "de": "德文", "pt": "葡萄牙文", "ru": "俄文",
            "th": "泰文", "vi": "越南文", "ar": "阿拉伯文", "it": "意大利文",
        }
        lang_name = LANG_NAMES.get(source_language, f"{source_language} 语言")

        batch_size = 15
        translated_segments = []

        for i in range(0, len(segments), batch_size):
            batch = segments[i:i + batch_size]
            texts = [f"{j+1}. {seg.text}" for j, seg in enumerate(batch)]
            prompt = (
                f"将以下{lang_name}字幕翻译成中文。\n\n"
                "要求：\n"
                "- 口语化、轻松活泼，像朋友聊天，不要书面语\n"
                "- 适当加 emoji 增加趣味性（每 3-5 条加一个，别每条都加）\n"
                "- 语气词可以保留（比如"哇""嘿""嗯"）\n"
                "- 保持简短，字幕不宜太长\n\n"
                "只输出翻译后的文本，每行一条，格式为 '序号. 翻译内容'：\n\n"
            ) + "\n".join(texts)

            result = await self.translation_agent.run(prompt)
            translated_lines = result.output.strip().split("\n")

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

    async def _burn_subtitles(self, video_path: Path, srt_path: Path, output_path: Path, topic: str = "", font_file: str = "") -> None:
        import shutil
        import tempfile
        from .font_selector import get_font_info, get_fonts_dir

        style = pick_subtitle_style(topic)
        font_info = get_font_info(font_file) if font_file else None
        font_name = font_info["font_family"] if font_info else SUBTITLE_CONFIG["FONT_NAME"]

        # 把 SRT 和字体复制到临时目录，ffmpeg 以 cwd=tmp_dir 运行，
        # 用相对路径 sub.srt 彻底规避 Windows 路径冒号转义问题
        tmp_dir = Path(tempfile.mkdtemp(prefix="subs_"))
        try:
            shutil.copy2(srt_path, tmp_dir / "sub.srt")
            env = None
            if font_info:
                shutil.copy2(get_fonts_dir() / font_file, tmp_dir / font_file)
                import os
                fonts_conf = tmp_dir / "fonts.conf"
                fonts_conf.write_text(
                    f'<?xml version="1.0"?>\n<fontconfig><dir>{tmp_dir}</dir></fontconfig>\n',
                    encoding="utf-8",
                )
                env = os.environ.copy()
                env["FONTCONFIG_FILE"] = str(fonts_conf)

            cmd = [
                "ffmpeg", "-i", str(video_path),
                "-vf", f"subtitles=sub.srt:force_style='FontName={font_name},FontSize={SUBTITLE_CONFIG['FONT_SIZE']},Bold=1,PrimaryColour={style['PrimaryColour']},OutlineColour={style['OutlineColour']},BackColour=&H80000000,Outline=3,Shadow=2,BorderStyle=1,MarginV=30'",
                "-c:a", "copy",
                "-y", str(output_path),
            ]

            logger.info(f"开始烧录字幕到视频（字体: {font_name}）...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(tmp_dir),
                env=env,
            )
            _, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"ffmpeg 字幕烧录失败: {stderr.decode()[-500:]}")

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError("烧录后的视频文件为空")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
