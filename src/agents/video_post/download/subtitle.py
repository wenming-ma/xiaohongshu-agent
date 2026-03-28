import asyncio
import os
import re
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ....utils.logger import get_logger
from ...shared.utils.transcription import extract_audio_track, get_transcription_model
from ..utils.tts_tags import DEFAULT_TONE_TAG, build_tts_text, normalize_tone_tag

logger = get_logger(__name__)

SUBTITLE_CONFIG = {
    "TARGET_LANGUAGE": "zh",
    "FONT_NAME": "Microsoft YaHei",
    "FONT_SIZE": 18,
    "ENABLE_TRANSLATION": True,
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TTS_SPLIT_RE = re.compile(r"(?<=[。！？；，、：,.!?;:])\s*")
_MAX_TTS_SEGMENT_CHARS = 22
_MAX_TTS_CHARS_PER_SECOND = 6.5
_MIN_TTS_SEGMENT_DURATION = 0.35
_SUBTITLE_TRANSLATION_BATCH_SIZE = 15
_SUBTITLE_TRANSLATION_MAX_CONCURRENCY = 5

SUBTITLE_STYLES = {
    "food": {
        "PrimaryColour": "&H0000FFFF",
        "OutlineColour": "&H00000000",
    },
    "fashion": {
        "PrimaryColour": "&H00B469FF",
        "OutlineColour": "&H00FFFFFF",
    },
    "travel": {
        "PrimaryColour": "&H00FFBF00",
        "OutlineColour": "&H00FFFFFF",
    },
    "tech": {
        "PrimaryColour": "&H00FFFF00",
        "OutlineColour": "&H00000000",
    },
    "fitness": {
        "PrimaryColour": "&H0000FF7F",
        "OutlineColour": "&H00000000",
    },
    "default": {
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
    },
}

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
    topic_lower = topic.lower()
    for style_name, keywords in _STYLE_KEYWORDS.items():
        if any(keyword in topic_lower for keyword in keywords):
            logger.info(f"字幕配色: {style_name}")
            return SUBTITLE_STYLES[style_name]
    logger.info("字幕配色: default")
    return SUBTITLE_STYLES["default"]


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


class SubtitleGenerationResult:
    def __init__(
        self,
        success: bool,
        segments: list[SubtitleSegment] | None = None,
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


class SubtitleGenerator:
    def __init__(
        self,
        *,
        subtitle_translation_agent: Any | None = None,
    ):
        self.subtitle_translation_agent = subtitle_translation_agent

    def _load_model(self) -> None:
        self.model = get_transcription_model()

    def _require_subtitle_translation_agent(self) -> Any:
        if self.subtitle_translation_agent is None:
            raise RuntimeError("字幕翻译审核 agent 未配置")
        return self.subtitle_translation_agent

    async def generate_and_burn(
        self,
        video_path: Path,
        output_path: Path,
        target_language: str = "zh",
        topic: str = "",
        font_file: str = "",
        font_name: str = "",
        font_path: Path | None = None,
    ) -> SubtitleGenerationResult:
        try:
            logger.info(f"开始生成字幕: {video_path.name}")
            _ = font_file

            audio_path = await self._extract_audio(video_path)
            segments, detected_lang = await self._transcribe_audio(audio_path)

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
                return SubtitleGenerationResult(
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

            return SubtitleGenerationResult(
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
            return SubtitleGenerationResult(success=False, error_message=str(e))

    async def _extract_audio(self, video_path: Path) -> Path:
        return await extract_audio_track(video_path)

    async def _transcribe_audio(self, audio_path: Path) -> tuple[list[SubtitleSegment], str]:
        self._load_model()

        logger.info("开始音频转录并生成字幕片段...")
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

        segments = [
            SubtitleSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text.strip(),
            )
            for segment in segments_list
        ]
        logger.info(f"转录完成: {len(segments)} 个字幕片段")
        return segments, detected_lang

    async def _assign_speakers(
        self,
        segments: list[SubtitleSegment],
        audio_path: Path,
    ) -> list[SubtitleSegment]:
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

            diarized_segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                diarized_segments.append((turn.start, turn.end, speaker))

            if not diarized_segments:
                return segments

            speaker_labels = sorted({speaker for _, _, speaker in diarized_segments})
            label_to_id = {label: index for index, label in enumerate(speaker_labels)}
            logger.info(f"识别到 {len(speaker_labels)} 个说话人: {speaker_labels}")

            for segment in segments:
                segment_mid = (segment.start + segment.end) / 2
                best_speaker = None
                best_overlap = 0.0
                for start, end, label in diarized_segments:
                    overlap = max(0.0, min(segment.end, end) - max(segment.start, start))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_speaker = label
                if best_speaker is None:
                    for start, end, label in diarized_segments:
                        if start <= segment_mid <= end:
                            best_speaker = label
                            break
                if best_speaker is not None:
                    segment.speaker_id = label_to_id[best_speaker]

            return segments
        except Exception as e:
            logger.warning(f"说话人识别失败（不影响字幕生成）: {e}")
            return segments

    async def _translate_segments_for_chinese_tts(
        self,
        segments: list[SubtitleSegment],
        *,
        source_language: str,
        translate_first: bool = True,
    ) -> list[SubtitleSegment]:
        normalized_source = [
            SubtitleSegment(
                start=segment.start,
                end=segment.end,
                text=_normalize_subtitle_text(segment.text),
                speaker_id=segment.speaker_id,
                tone_tag=normalize_tone_tag(segment.tone_tag or DEFAULT_TONE_TAG),
            )
            for segment in segments
        ]
        if not normalized_source:
            return []

        subtitle_translation_agent = self._require_subtitle_translation_agent()
        batches = [
            normalized_source[index:index + _SUBTITLE_TRANSLATION_BATCH_SIZE]
            for index in range(0, len(normalized_source), _SUBTITLE_TRANSLATION_BATCH_SIZE)
        ]
        results_by_index: dict[int, list[SubtitleSegment]] = {}
        done_count = 0
        semaphore = asyncio.Semaphore(_SUBTITLE_TRANSLATION_MAX_CONCURRENCY)

        async def _translate_batch(batch_index: int, batch: list[SubtitleSegment]) -> None:
            nonlocal done_count

            async with semaphore:
                translated_batch = await subtitle_translation_agent.forward(
                    batch,
                    source_language=source_language or "mixed",
                    translate_first=translate_first,
                )

            results_by_index[batch_index] = translated_batch
            done_count += 1
            logger.info(
                f"字幕翻译审核进度: {done_count}/{len(batches)} 批 "
                f"({min(done_count * _SUBTITLE_TRANSLATION_BATCH_SIZE, len(normalized_source))}/"
                f"{len(normalized_source)})"
            )

        await asyncio.gather(
            *[_translate_batch(batch_index, batch) for batch_index, batch in enumerate(batches)]
        )

        translated_segments: list[SubtitleSegment] = []
        for batch_index in range(len(batches)):
            translated_segments.extend(results_by_index[batch_index])

        return [
            SubtitleSegment(
                start=segment.start,
                end=segment.end,
                text=_normalize_subtitle_text(segment.text),
                speaker_id=segment.speaker_id,
                tone_tag=normalize_tone_tag(segment.tone_tag or DEFAULT_TONE_TAG),
            )
            for segment in translated_segments
        ]

    def _build_tts_segments(self, segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
        tts_segments: list[SubtitleSegment] = []
        cursor = 0.0

        for segment in segments:
            text = _normalize_subtitle_text(segment.text)
            if not text:
                continue

            duration = max(segment.end - segment.start, 0.0)
            density = (_visible_text_length(text) / duration) if duration > 1e-6 else float("inf")
            parts = _split_text_for_tts(text)
            should_split = (
                len(parts) > 1
                or _visible_text_length(text) > _MAX_TTS_SEGMENT_CHARS
                or density > _MAX_TTS_CHARS_PER_SECOND
            )
            effective_parts = parts if should_split else [text]
            part_durations = _allocate_tts_durations(effective_parts, duration)

            part_cursor = max(segment.start, cursor)
            for part, part_duration in zip(effective_parts, part_durations):
                start = part_cursor
                end = start + part_duration
                tts_segments.append(
                    SubtitleSegment(
                        start=start,
                        end=end,
                        text=part,
                        speaker_id=segment.speaker_id,
                        tone_tag=normalize_tone_tag(segment.tone_tag or DEFAULT_TONE_TAG),
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
        has_speakers = any(segment.speaker_id != 0 for segment in segments)
        with open(output_path, "w", encoding="utf-8") as handle:
            for index, segment in enumerate(segments, 1):
                start = self._format_timestamp(segment.start)
                end = self._format_timestamp(segment.end)
                text = segment.text
                if include_tone_tags:
                    text = build_tts_text(text, segment.tone_tag or DEFAULT_TONE_TAG)
                if has_speakers:
                    text = f"[S{segment.speaker_id}] {text}"
                handle.write(f"{index}\n{start} --> {end}\n{text}\n\n")

    def _format_timestamp(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        whole_seconds = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"

    async def _burn_subtitles(
        self,
        video_path: Path,
        srt_path: Path,
        output_path: Path,
        topic: str = "",
        font_name: str = "",
        font_path: Path | None = None,
    ) -> None:
        style = pick_subtitle_style(topic)
        resolved_font_name = font_name or SUBTITLE_CONFIG["FONT_NAME"]

        tmp_dir = Path(tempfile.mkdtemp(prefix="subs_"))
        try:
            shutil.copy2(srt_path, tmp_dir / "sub.srt")
            env = None
            if font_path and font_path.exists():
                shutil.copy2(font_path, tmp_dir / font_path.name)
                fonts_conf = tmp_dir / "fonts.conf"
                fonts_conf.write_text(
                    f'<?xml version="1.0"?>\n<fontconfig><dir>{tmp_dir}</dir></fontconfig>\n',
                    encoding="utf-8",
                )
                env = os.environ.copy()
                env["FONTCONFIG_FILE"] = str(fonts_conf)

            subtitle_filter = (
                "subtitles=sub.srt:force_style="
                f"'FontName={resolved_font_name},"
                f"FontSize={SUBTITLE_CONFIG['FONT_SIZE']},"
                f"Bold=1,"
                f"PrimaryColour={style['PrimaryColour']},"
                f"OutlineColour={style['OutlineColour']},"
                "BackColour=&H80000000,"
                "Outline=2,"
                "Shadow=1,"
                "BorderStyle=1,"
                "MarginV=30'"
            )
            cmd = [
                "ffmpeg",
                "-hwaccel",
                "cuda",
                "-i",
                str(video_path),
                "-vf",
                subtitle_filter,
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-cq",
                "20",
                "-c:a",
                "copy",
                "-y",
                str(output_path),
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
