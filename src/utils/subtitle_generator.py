import asyncio
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional
from threading import Lock

# 设置离线模式和禁用警告
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# 添加 CUDA cuBLAS DLL 路径到 PATH
_venv_nvidia_bin = Path(__file__).parent.parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
if _venv_nvidia_bin.exists():
    os.environ["PATH"] = str(_venv_nvidia_bin) + os.pathsep + os.environ.get("PATH", "")

from faster_whisper import WhisperModel
from pydantic import BaseModel, Field

from ..utils.logger import get_logger
from .tts_tags import DEFAULT_TONE_TAG, build_tts_text, normalize_tone_tag

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
    "FONT_SIZE": 18,
    "ENABLE_TRANSLATION": True,
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CHINESE_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_FOREIGN_CHAR_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af\u0400-\u04ff]")
_TTS_SPLIT_RE = re.compile(r"(?<=[。！？；，、：,.!?;:])\s*")
_MAX_TTS_SEGMENT_CHARS = 22
_MAX_TTS_CHARS_PER_SECOND = 6.5
_MIN_TTS_SEGMENT_DURATION = 0.35
_FOREIGN_RATIO_THRESHOLD = 0.15
_FOREIGN_MIN_CHARS = 2

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


_shared_whisper_model: Optional[WhisperModel] = None
_shared_whisper_model_lock = Lock()


def _get_shared_whisper_model() -> WhisperModel:
    global _shared_whisper_model
    if _shared_whisper_model is not None:
        return _shared_whisper_model

    with _shared_whisper_model_lock:
        if _shared_whisper_model is None:
            logger.info("加载 Whisper 模型（本地离线模式）...")
            _shared_whisper_model = WhisperModel(
                SUBTITLE_CONFIG["WHISPER_MODEL"],
                device=SUBTITLE_CONFIG["WHISPER_DEVICE"],
                compute_type=SUBTITLE_CONFIG["WHISPER_COMPUTE_TYPE"],
                local_files_only=True,
            )
            logger.info("Whisper 模型加载完成")
    return _shared_whisper_model


def release_whisper_model() -> None:
    import gc
    global _shared_whisper_model
    with _shared_whisper_model_lock:
        if _shared_whisper_model is not None:
            del _shared_whisper_model
            _shared_whisper_model = None
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass


def _normalize_subtitle_text(text: str) -> str:
    cleaned = _HTML_TAG_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _visible_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", _normalize_subtitle_text(text)))


def _split_text_for_tts(text: str, max_chars: int = _MAX_TTS_SEGMENT_CHARS) -> list[str]:
    normalized = _normalize_subtitle_text(text)
    if not normalized:
        return []

    chunks = [part.strip() for part in _TTS_SPLIT_RE.split(normalized) if part.strip()]
    if not chunks:
        chunks = [normalized]

    results: list[str] = []
    for chunk in chunks:
        if _visible_text_length(chunk) <= max_chars:
            results.append(chunk)
            continue

        words = chunk.split(" ")
        if len(words) > 1:
            current_words: list[str] = []
            for word in words:
                candidate = " ".join([*current_words, word]).strip()
                if current_words and _visible_text_length(candidate) > max_chars:
                    results.append(" ".join(current_words).strip())
                    current_words = [word]
                else:
                    current_words.append(word)
            if current_words:
                results.append(" ".join(current_words).strip())
            continue

        cursor = 0
        while cursor < len(chunk):
            next_cursor = min(cursor + max_chars, len(chunk))
            results.append(chunk[cursor:next_cursor].strip())
            cursor = next_cursor

    return [item for item in results if item]


def _allocate_tts_durations(parts: list[str], total_duration: float) -> list[float]:
    if not parts:
        return []

    total_duration = max(total_duration, _MIN_TTS_SEGMENT_DURATION * len(parts))

    weights = [max(_visible_text_length(part), 1) for part in parts]
    total_weight = sum(weights) or len(parts)
    durations = [total_duration * weight / total_weight for weight in weights]

    shortfall = 0.0
    for index, value in enumerate(durations):
        if value < _MIN_TTS_SEGMENT_DURATION:
            shortfall += _MIN_TTS_SEGMENT_DURATION - value
            durations[index] = _MIN_TTS_SEGMENT_DURATION

    if shortfall > 0:
        adjustable = [
            idx for idx, value in enumerate(durations)
            if value > _MIN_TTS_SEGMENT_DURATION + 1e-6
        ]
        while shortfall > 1e-6 and adjustable:
            adjustable_total = sum(
                durations[idx] - _MIN_TTS_SEGMENT_DURATION for idx in adjustable
            )
            if adjustable_total <= 1e-6:
                break
            next_adjustable: list[int] = []
            for idx in adjustable:
                available = durations[idx] - _MIN_TTS_SEGMENT_DURATION
                reduction = min(shortfall * (available / adjustable_total), available)
                durations[idx] -= reduction
                shortfall -= reduction
                if durations[idx] > _MIN_TTS_SEGMENT_DURATION + 1e-6:
                    next_adjustable.append(idx)
            adjustable = next_adjustable

    return durations


def pick_subtitle_style(topic: str) -> dict:
    """根据话题关键词选择字幕配色方案"""
    topic_lower = topic.lower()
    for style_name, keywords in _STYLE_KEYWORDS.items():
        if any(kw in topic_lower for kw in keywords):
            logger.info(f"字幕配色: {style_name}")
            return SUBTITLE_STYLES[style_name]
    logger.info("字幕配色: default")
    return SUBTITLE_STYLES["default"]


async def _check_has_audio(video_path: Path) -> bool:
    probe = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0",
        str(video_path),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, _ = await probe.communicate()
    return bool(stdout.strip())


class SubtitleSegment:
    def __init__(
        self,
        start: float,
        end: float,
        text: str,
        speaker_id: int = 0,
        tone_tag: str = "",
    ):
        self.start = start
        self.end = end
        self.text = text
        self.speaker_id = speaker_id
        self.tone_tag = tone_tag


class SubtitleResult:
    def __init__(
        self,
        success: bool,
        segments: list[SubtitleSegment] = None,
        language: str = "",
        translated: bool = False,
        srt_path: str = "",
        tts_srt_path: str = "",
        video_with_subs: str = "",
        error_message: str = "",
    ):
        self.success = success
        self.segments = segments or []
        self.language = language
        self.translated = translated
        self.srt_path = srt_path
        self.tts_srt_path = tts_srt_path
        self.video_with_subs = video_with_subs
        self.error_message = error_message


class TranslationLine(BaseModel):
    index: int = Field(ge=1)
    tone_tag: str = DEFAULT_TONE_TAG
    text: str = ""


class TranslationBatch(BaseModel):
    lines: list[TranslationLine]


class SubtitleTranslationReview(BaseModel):
    passed: bool = False
    issues: list[str] = []
    summary: str = ""


class WhisperTranscriber:
    """使用本地 Whisper 模型进行转录（仅文本，用于 ContentAgent）"""

    def _load_whisper_model(self):
        self.model = _get_shared_whisper_model()

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
        if not await _check_has_audio(video_path):
            raise RuntimeError("视频无音频轨道，无法提取音频")
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

    def __init__(
        self,
        *,
        translation_agent: Any | None = None,
        translation_reviewer: Any | None = None,
    ):
        self.translation_agent = translation_agent
        self.translation_reviewer = translation_reviewer

    def _load_whisper_model(self):
        self.model = _get_shared_whisper_model()

    def _require_translation_agent(self) -> Any:
        if self.translation_agent is None:
            raise RuntimeError("字幕翻译 agent 未配置")
        return self.translation_agent

    def _require_translation_reviewer(self) -> Any:
        if self.translation_reviewer is None:
            raise RuntimeError("字幕翻译审核 agent 未配置")
        return self.translation_reviewer

    async def generate_and_burn(
        self,
        video_path: Path,
        output_path: Path,
        target_language: str = "zh",
        topic: str = "",
        font_file: str = "",
        font_name: str = "",
        font_path: Path | None = None,
    ) -> SubtitleResult:
        try:
            logger.info(f"开始生成字幕: {video_path.name}")
            _ = font_file

            audio_path = await self._extract_audio(video_path)

            segments, detected_lang = await self._transcribe_with_whisper(audio_path)

            if segments:
                segments = await self._assign_speakers(segments, audio_path)

            if audio_path.exists():
                audio_path.unlink(missing_ok=True)

            translated = False
            if target_language == "zh":
                translate_first = detected_lang != "zh" and SUBTITLE_CONFIG["ENABLE_TRANSLATION"]
                if translate_first:
                    logger.info(f"检测到 {detected_lang}，开始翻译成中文...")
                segments = await self._translate_segments_for_chinese_tts(
                    segments,
                    source_language=detected_lang,
                    translate_first=translate_first,
                )
                translated = translate_first

            if not segments:
                logger.warning("无字幕片段，跳过烧录")
                return SubtitleResult(
                    success=False,
                    segments=[],
                    language=detected_lang,
                    error_message="转录无结果（视频可能无人声）",
                )

            srt_path = output_path.with_suffix(".srt")
            tts_srt_path = output_path.with_name(f"{output_path.stem}_tts.srt")
            tts_segments = self._build_tts_segments(segments)
            self._generate_srt(segments, srt_path, include_tone_tags=False)
            logger.info(f"屏显 SRT 文件生成: {srt_path}")
            self._generate_srt(tts_segments, tts_srt_path, include_tone_tags=True)
            logger.info(f"TTS SRT 文件生成: {tts_srt_path}")

            await self._burn_subtitles(
                video_path,
                srt_path,
                output_path,
                topic=topic,
                font_name=font_name,
                font_path=font_path,
            )
            logger.info(f"字幕烧录完成: {output_path}")

            return SubtitleResult(
                success=True,
                segments=segments,
                language=detected_lang,
                translated=translated,
                srt_path=str(srt_path),
                tts_srt_path=str(tts_srt_path),
                video_with_subs=str(output_path),
            )

        except Exception as e:
            logger.error(f"字幕生成失败: {e}")
            return SubtitleResult(
                success=False,
                error_message=str(e),
            )

    async def _extract_audio(self, video_path: Path) -> Path:
        if not await _check_has_audio(video_path):
            raise RuntimeError("视频无音频轨道，无法提取音频")
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

    async def _assign_speakers(self, segments: list[SubtitleSegment], audio_path: Path) -> list[SubtitleSegment]:
        try:
            from pyannote.audio import Pipeline as PyannotePipeline
        except ImportError:
            logger.debug("pyannote-audio 未安装，跳过说话人识别")
            return segments

        hf_token = os.environ.get("HF_TOKEN", "")
        if not hf_token:
            logger.debug("未配置 HF_TOKEN，跳过说话人识别")
            return segments

        try:
            loop = asyncio.get_event_loop()

            def _diarize():
                pipeline = PyannotePipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=hf_token,
                )
                return pipeline(str(audio_path))

            logger.info("开始说话人识别（pyannote）...")
            diarization = await loop.run_in_executor(None, _diarize)

            dia_segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                dia_segments.append((turn.start, turn.end, speaker))

            if not dia_segments:
                return segments

            speaker_labels = sorted(set(s[2] for s in dia_segments))
            label_to_id = {label: i for i, label in enumerate(speaker_labels)}
            logger.info(f"识别到 {len(speaker_labels)} 个说话人: {speaker_labels}")

            for seg in segments:
                seg_mid = (seg.start + seg.end) / 2
                best_speaker = None
                best_overlap = 0
                for ds, de, dl in dia_segments:
                    overlap = max(0, min(seg.end, de) - max(seg.start, ds))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_speaker = dl
                if best_speaker is None:
                    for ds, de, dl in dia_segments:
                        if ds <= seg_mid <= de:
                            best_speaker = dl
                            break
                if best_speaker is not None:
                    seg.speaker_id = label_to_id[best_speaker]

            return segments
        except Exception as e:
            logger.warning(f"说话人识别失败（不影响字幕生成）: {e}")
            return segments

    async def _rewrite_segments_to_chinese(
        self,
        segments: list[SubtitleSegment],
        *,
        source_language: str,
        mode: str,
        current_segments: list[SubtitleSegment] | None = None,
        feedback: str = "",
    ) -> list[SubtitleSegment]:
        translation_agent = self._require_translation_agent()

        lang_names = {
            "en": "英文", "ja": "日文", "ko": "韩文", "fr": "法文",
            "es": "西班牙文", "de": "德文", "pt": "葡萄牙文", "ru": "俄文",
            "th": "泰文", "vi": "越南文", "ar": "阿拉伯文", "it": "意大利文",
            "mixed": "混合语言",
        }
        lang_name = lang_names.get(source_language, f"{source_language} 语言")

        batch_size = 10 if mode == "revise" else 15
        max_concurrency = 5
        semaphore = asyncio.Semaphore(max_concurrency)

        batches: list[list[SubtitleSegment]] = []
        for index in range(0, len(segments), batch_size):
            batches.append(segments[index:index + batch_size])

        results_by_index: dict[int, list[SubtitleSegment]] = {}
        done_count = 0
        has_multiple_speakers = len(set(seg.speaker_id for seg in segments)) > 1

        async def _rewrite_batch(batch_idx: int, batch: list[SubtitleSegment]) -> None:
            nonlocal done_count
            current_batch = current_segments[batch_idx * batch_size:(batch_idx + 1) * batch_size] if current_segments else None
            if has_multiple_speakers:
                texts = [f"{line_idx + 1}. [说话人{seg.speaker_id}] {seg.text}" for line_idx, seg in enumerate(batch)]
            else:
                texts = [f"{line_idx + 1}. {seg.text}" for line_idx, seg in enumerate(batch)]

            speaker_instruction = ""
            if has_multiple_speakers:
                speaker_instruction = (
                    "- 每行开头的 [说话人N] 只是上下文，不要出现在输出里\n"
                    "- 说话人不同可以保留不同语气\n"
                )

            if mode == "revise" and current_batch is not None:
                if has_multiple_speakers:
                    current_texts = [
                        f"{line_idx + 1}. [说话人{seg.speaker_id}] {seg.text}"
                        for line_idx, seg in enumerate(current_batch)
                    ]
                else:
                    current_texts = [f"{line_idx + 1}. {seg.text}" for line_idx, seg in enumerate(current_batch)]

                task_intro = f"请基于原始{lang_name}字幕、当前中文字幕和审核反馈，输出一版修订后的完整中文字幕。"
                requirements = (
                    "- 必须逐条输出完整结果，不能只输出修改建议\n"
                    "- 每一条都必须是自然、简短、适合中文 TTS 朗读的中文\n"
                    "- 可以保留少量已经融入中文表达的常见英文单词，如 app、API、Wi-Fi、iPhone、OK\n"
                    "- 不要保留完整外语短句、大段外语片段或明显不自然的混写\n"
                    "- 尽量保留当前版本已经正确的内容，只修复审核指出的问题\n"
                    "- 不要输出 emoji、括号说明或解释性文字\n"
                )
                prompt = (
                    f"{task_intro}\n\n"
                    "审核反馈：\n"
                    f"{feedback or '请修复所有非中文和不自然表达。'}\n\n"
                    "原始字幕：\n"
                    + "\n".join(texts)
                    + "\n\n当前中文字幕：\n"
                    + "\n".join(current_texts)
                    + "\n\n修订要求：\n"
                    + requirements
                    + speaker_instruction
                    + "- 为每条字幕单独给一个语气 tag，供 Fish/S2 TTS 使用\n"
                    + "- tag 只允许简短英文短语：1 到 3 个单词，只能包含英文字母和空格\n"
                    + "- tag 要能直接放进 [tag] 形式里，例如 neutral, friendly, excited, serious, whisper\n"
                    + "- 不要输出方括号，不要输出中文 tag，不要输出长句 tag\n"
                    + "- 如果语气不明显，用 neutral\n"
                    + "- 按结构化结果输出，每条包含 index、tone_tag、text\n"
                )
            else:
                task_intro = f"将以下{lang_name}字幕翻译成中文。"
                requirements = (
                    "- 口语化、轻松活泼，像朋友聊天，不要书面语\n"
                    "- 适当保留语气词，保持简短，适合视频字幕阅读\n"
                    "- 输出必须以中文为主\n"
                    "- 可以保留少量已经融入中文表达的常见英文单词，如 app、API、Wi-Fi、iPhone、OK\n"
                    "- 不要保留原语言整句或大段外语片段\n"
                )
                prompt = (
                    f"{task_intro}\n\n"
                    "要求：\n"
                    f"{requirements}"
                    f"{speaker_instruction}"
                    "- 为每条字幕单独给一个语气 tag，供 Fish/S2 TTS 使用\n"
                    "- tag 只允许简短英文短语：1 到 3 个单词，只能包含英文字母和空格\n"
                    "- tag 要能直接放进 [tag] 形式里，例如 neutral, friendly, excited, serious, whisper\n"
                    "- 不要输出方括号，不要输出中文 tag，不要输出长句 tag\n"
                    "- 如果语气不明显，用 neutral\n"
                    "- 按结构化结果输出，每条包含 index、tone_tag、text\n\n"
                ) + "\n".join(texts)

            async with semaphore:
                result = await translation_agent.run(prompt)

            translated_lines = {line.index: line for line in result.output.lines}
            batch_result: list[SubtitleSegment] = []
            for line_idx, seg in enumerate(batch, start=1):
                translated_line = translated_lines.get(line_idx)
                translated_text = (
                    _normalize_subtitle_text(translated_line.text)
                    if translated_line is not None
                    else ""
                )
                if not translated_text:
                    if current_batch is not None and line_idx - 1 < len(current_batch):
                        translated_text = _normalize_subtitle_text(current_batch[line_idx - 1].text)
                    else:
                        translated_text = _normalize_subtitle_text(seg.text)

                tone_source = translated_line.tone_tag if translated_line is not None else seg.tone_tag
                tone_tag = normalize_tone_tag(tone_source or seg.tone_tag or DEFAULT_TONE_TAG)
                batch_result.append(
                    SubtitleSegment(
                        start=seg.start,
                        end=seg.end,
                        text=translated_text,
                        speaker_id=seg.speaker_id,
                        tone_tag=tone_tag,
                    )
                )

            results_by_index[batch_idx] = batch_result
            done_count += 1
            label = "修订" if mode == "revise" else "翻译"
            logger.info(
                f"{label}进度: {done_count}/{len(batches)} 批 "
                f"({min(done_count * batch_size, len(segments))}/{len(segments)})"
            )

        await asyncio.gather(*[_rewrite_batch(idx, batch) for idx, batch in enumerate(batches)])

        rewritten_segments: list[SubtitleSegment] = []
        for idx in range(len(batches)):
            rewritten_segments.extend(results_by_index[idx])
        return rewritten_segments

    async def _review_translated_segments(
        self,
        source_segments: list[SubtitleSegment],
        translated_segments: list[SubtitleSegment],
        source_language: str,
    ) -> SubtitleTranslationReview:
        translation_reviewer = self._require_translation_reviewer()

        lang_names = {
            "en": "英文", "ja": "日文", "ko": "韩文", "fr": "法文",
            "es": "西班牙文", "de": "德文", "pt": "葡萄牙文", "ru": "俄文",
            "th": "泰文", "vi": "越南文", "ar": "阿拉伯文", "it": "意大利文",
            "mixed": "混合语言", "zh": "中文字幕",
        }
        lang_name = lang_names.get(source_language or "mixed", f"{source_language} 字幕")
        has_multiple_speakers = len(set(seg.speaker_id for seg in translated_segments)) > 1

        if has_multiple_speakers:
            source_lines = [
                f"{idx + 1}. [说话人{seg.speaker_id}] {seg.text}"
                for idx, seg in enumerate(source_segments)
            ]
            translated_lines = [
                f"{idx + 1}. [说话人{seg.speaker_id}] {seg.text}"
                for idx, seg in enumerate(translated_segments)
            ]
        else:
            source_lines = [f"{idx + 1}. {seg.text}" for idx, seg in enumerate(source_segments)]
            translated_lines = [f"{idx + 1}. {seg.text}" for idx, seg in enumerate(translated_segments)]

        prompt = (
            f"请审核以下{lang_name}转中文后的字幕结果。\n\n"
            "审核标准：\n"
            "- 每一行都必须是自然、完整、可直接朗读的中文\n"
            "- 允许少量已经融入中文表达的英文单词，如 app、API、Wi-Fi、iPhone、OK\n"
            "- 不能残留完整外语短句、大段外语片段、或明显破坏中文口播自然度的混写\n"
            "- 不能出现明显不适合中文 TTS 的表达\n"
            "- 语义应尽量忠实原文，不要漏译关键信息\n"
            "- 只有全部通过时，`passed` 才能为 true\n"
            "- 如果不通过，issues 必须给出可执行反馈，并尽量指出具体行号\n\n"
            "原始字幕：\n"
            + "\n".join(source_lines)
            + "\n\n当前中文字幕：\n"
            + "\n".join(translated_lines)
        )
        result = await translation_reviewer.run(prompt)
        return result.output

    @staticmethod
    def _build_translation_review_feedback(review: SubtitleTranslationReview) -> str:
        lines = [review.summary.strip() or "字幕中文审核未通过，请根据问题修订。"]
        for issue in review.issues:
            cleaned = issue.strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        return "\n".join(lines)

    async def _translate_segments_for_chinese_tts(
        self,
        segments: list[SubtitleSegment],
        *,
        source_language: str,
        translate_first: bool = True,
    ) -> list[SubtitleSegment]:
        normalized_source = [
            SubtitleSegment(
                start=seg.start,
                end=seg.end,
                text=_normalize_subtitle_text(seg.text),
                speaker_id=seg.speaker_id,
                tone_tag=normalize_tone_tag(seg.tone_tag or DEFAULT_TONE_TAG),
            )
            for seg in segments
        ]
        current_segments = (
            await self._rewrite_segments_to_chinese(
                normalized_source,
                source_language=source_language or "mixed",
                mode="translate",
            )
            if translate_first
            else normalized_source
        )

        max_rounds = 3
        last_review: SubtitleTranslationReview | None = None
        for round_index in range(max_rounds):
            last_review = await self._review_translated_segments(
                normalized_source,
                current_segments,
                source_language=source_language or "mixed",
            )
            if last_review.passed:
                return [
                    SubtitleSegment(
                        start=seg.start,
                        end=seg.end,
                        text=_normalize_subtitle_text(seg.text),
                        speaker_id=seg.speaker_id,
                        tone_tag=normalize_tone_tag(seg.tone_tag or DEFAULT_TONE_TAG),
                    )
                    for seg in current_segments
                ]

            feedback = self._build_translation_review_feedback(last_review)
            logger.warning(f"字幕中文审核未通过 (第{round_index + 1}轮): {last_review.summary or feedback}")
            current_segments = await self._rewrite_segments_to_chinese(
                normalized_source,
                source_language=source_language or "mixed",
                mode="revise",
                current_segments=current_segments,
                feedback=feedback,
            )

        raise RuntimeError(
            "字幕中文审核未通过，达到最大修订轮数: "
            f"{self._build_translation_review_feedback(last_review or SubtitleTranslationReview())}"
        )

    def _build_tts_segments(self, segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
        tts_segments: list[SubtitleSegment] = []
        cursor = 0.0

        for seg in segments:
            text = _normalize_subtitle_text(seg.text)
            if not text:
                continue

            duration = max(seg.end - seg.start, 0.0)
            density = (_visible_text_length(text) / duration) if duration > 1e-6 else float("inf")
            parts = _split_text_for_tts(text)
            should_split = (
                len(parts) > 1
                or _visible_text_length(text) > _MAX_TTS_SEGMENT_CHARS
                or density > _MAX_TTS_CHARS_PER_SECOND
            )
            effective_parts = parts if should_split else [text]
            part_durations = _allocate_tts_durations(effective_parts, duration)

            part_cursor = max(seg.start, cursor)
            for part, part_duration in zip(effective_parts, part_durations):
                start = part_cursor
                end = start + part_duration
                tts_segments.append(
                    SubtitleSegment(
                        start=start,
                        end=end,
                        text=part,
                        speaker_id=seg.speaker_id,
                        tone_tag=normalize_tone_tag(seg.tone_tag or DEFAULT_TONE_TAG),
                    )
                )
                part_cursor = end

            cursor = part_cursor

        return tts_segments

    def _generate_srt(
        self,
        segments: list[SubtitleSegment],
        output_path: Path,
        *,
        include_tone_tags: bool,
    ) -> None:
        has_speakers = any(seg.speaker_id != 0 for seg in segments)
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = self._format_timestamp(seg.start)
                end = self._format_timestamp(seg.end)
                text = seg.text
                if include_tone_tags:
                    text = build_tts_text(text, seg.tone_tag or DEFAULT_TONE_TAG)
                if has_speakers:
                    text = f"[S{seg.speaker_id}] {text}"
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    def _format_timestamp(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    async def _burn_subtitles(
        self,
        video_path: Path,
        srt_path: Path,
        output_path: Path,
        topic: str = "",
        font_name: str = "",
        font_path: Path | None = None,
    ) -> None:
        import shutil
        import tempfile

        style = pick_subtitle_style(topic)
        resolved_font_name = font_name or SUBTITLE_CONFIG["FONT_NAME"]

        # 把 SRT 和字体复制到临时目录，ffmpeg 以 cwd=tmp_dir 运行，
        # 用相对路径 sub.srt 彻底规避 Windows 路径冒号转义问题
        tmp_dir = Path(tempfile.mkdtemp(prefix="subs_"))
        try:
            shutil.copy2(srt_path, tmp_dir / "sub.srt")
            env = None
            if font_path and font_path.exists():
                shutil.copy2(font_path, tmp_dir / font_path.name)
                import os
                fonts_conf = tmp_dir / "fonts.conf"
                fonts_conf.write_text(
                    f'<?xml version="1.0"?>\n<fontconfig><dir>{tmp_dir}</dir></fontconfig>\n',
                    encoding="utf-8",
                )
                env = os.environ.copy()
                env["FONTCONFIG_FILE"] = str(fonts_conf)

            sub_filter = f"subtitles=sub.srt:force_style='FontName={resolved_font_name},FontSize={SUBTITLE_CONFIG['FONT_SIZE']},Bold=1,PrimaryColour={style['PrimaryColour']},OutlineColour={style['OutlineColour']},BackColour=&H80000000,Outline=2,Shadow=1,BorderStyle=1,MarginV=30'"
            cmd = [
                "ffmpeg", "-hwaccel", "cuda", "-i", str(video_path),
                "-vf", sub_filter,
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
                "-c:a", "copy",
                "-y", str(output_path),
            ]

            logger.info(f"开始烧录字幕到视频（字体: {resolved_font_name}）...")
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
