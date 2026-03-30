import asyncio
import os
import re
from pathlib import Path
from typing import Any, List

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoSource, DownloadResult, SubtitleResult, SubtitleSegment, Platform
from ....utils.logger import get_logger
from ....utils.providers import get_text_model
from ...shared.utils.asr import (
    AudioTranscriber,
    extract_audio_track,
    get_asr_service,
    release_asr_resources,
)
from ..utils.subtitle_helpers import (
    SUBTITLE_CONFIG,
    build_tts_segments,
    burn_subtitles,
    generate_srt,
    normalize_subtitle_text,
)
from ..utils.tts_tags import DEFAULT_TONE_TAG
from .subtitle_translation_agent import SubtitleTranslationAgent
from .prompts import (
    download_font_selector_system_prompt,
    download_font_selector_user_prompt,
    download_pick_system_prompt,
    download_pick_user_prompt,
)

logger = get_logger(__name__)

BEST_QUALITY_FORMAT = "bestvideo*+bestaudio/best"
TARGET_DOWNLOAD_SHORT_EDGE = 1080
DEFAULT_FORMAT_SORT = [
    f"+res:{TARGET_DOWNLOAD_SHORT_EDGE}",
    "+size",
    "+br",
]
FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"

PLATFORM_OPTS = {
    Platform.YOUTUBE: {
        "format": BEST_QUALITY_FORMAT,
        "format_sort": DEFAULT_FORMAT_SORT,
    },
    Platform.X: {
        "format": BEST_QUALITY_FORMAT,
        "format_sort": DEFAULT_FORMAT_SORT,
    },
    Platform.INSTAGRAM: {
        "format": BEST_QUALITY_FORMAT,
        "format_sort": DEFAULT_FORMAT_SORT,
    },
    Platform.FACEBOOK: {
        "format": BEST_QUALITY_FORMAT,
        "format_sort": DEFAULT_FORMAT_SORT,
    },
    Platform.TIKTOK: {
        "format": BEST_QUALITY_FORMAT,
        "format_sort": DEFAULT_FORMAT_SORT,
    },
}

MIN_FILE_SIZE = 100 * 1024  # 100KB
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
DOWNLOAD_TIMEOUT = 1200  # 20 minutes
DEFAULT_PRESELECT_TOP_K = 3
DEFAULT_FONT_FILE = "ZCOOLKuaiLe-Regular.ttf"
_SUBTITLE_TRANSLATION_BATCH_SIZE = 15
_SUBTITLE_TRANSLATION_MAX_CONCURRENCY = 5

FONT_CATALOG = [
    {
        "file_name": "KNBobohei-Bold.ttf",
        "font_family": "KN Bobohei",
        "display_name": "荆南波波黑",
        "style": "卡通俏皮，笔画带波浪感，适合搞笑、萌宠、可爱向内容",
    },
    {
        "file_name": "KNMaiyuan-Regular.ttf",
        "font_family": "KN Maiyuan",
        "display_name": "荆南麦圆体",
        "style": "萌系圆润，笔画两端饱满，适合儿童、亲子、萌系内容",
    },
    {
        "file_name": "ZCOOLKuaiLe-Regular.ttf",
        "font_family": "ZCOOL KuaiLe",
        "display_name": "站酷快乐体",
        "style": "活泼有趣，笔画灵活跳跃，适合轻松娱乐、美食探店",
    },
    {
        "file_name": "ZCOOLQingKeHuangYou-Regular.ttf",
        "font_family": "ZCOOL QingKe HuangYou",
        "display_name": "站酷庆科黄油体",
        "style": "全圆角处理，笨拙可爱，适合美食、甜品、温馨生活",
    },
    {
        "file_name": "LXGWWenKai-Medium.ttf",
        "font_family": "LXGW WenKai Medium",
        "display_name": "霞鹜文楷",
        "style": "文艺雅致的楷体风格，适合文化、读书、旅行、人文纪实",
    },
    {
        "file_name": "Yozai-Medium.ttf",
        "font_family": "Yozai Medium",
        "display_name": "悠哉字体",
        "style": "悠游自在的手写风，适合日常vlog、慢生活、手帐风格",
    },
    {
        "file_name": "Xiaolai-Regular.ttf",
        "font_family": "小賴字體",
        "display_name": "小赖字体",
        "style": "天然呆萌的手写风格，适合二次元、动漫、可爱日常",
    },
    {
        "file_name": "SmileySans-Oblique.ttf",
        "font_family": "Smiley Sans Oblique",
        "display_name": "得意黑",
        "style": "窄体斜字设计感强，融合手绘美术字造型，适合潮流、时尚、创意、科技",
    },
    {
        "file_name": "DouyinSansBold.ttf",
        "font_family": "DouyinSans",
        "display_name": "抖音美好体",
        "style": "简洁现代的品牌字体，适合知识分享、科普、测评、正式内容",
    },
    {
        "file_name": "LXGWMarkerGothic-Regular.ttf",
        "font_family": "LXGW Marker Gothic",
        "display_name": "霞鹜漫黑",
        "style": "马克笔手写风格，活泼个性，适合手工DIY、绘画、创意教程",
    },
]
_CATALOG_BY_FILE = {font["file_name"]: font for font in FONT_CATALOG}
_FONT_LIST_TEXT = "\n".join(
    f'- **{font["display_name"]}** (file: `{font["file_name"]}`): {font["style"]}'
    for font in FONT_CATALOG
)


class VideoPick(BaseModel):
    best_index: int = Field(description="最佳视频的序号（从 0 开始）")
    reason: str = Field(description="选择理由")


class FontSelection(BaseModel):
    font_file: str = Field(description="选中的字体文件名")
    reason: str = Field(description="选择理由")


class _YtDlpLogger:
    @staticmethod
    def debug(msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        logger.debug("yt-dlp: %s", msg)

    @staticmethod
    def info(msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    @staticmethod
    def warning(msg: str) -> None:
        logger.debug("yt-dlp warning: %s", msg)

    @staticmethod
    def error(msg: str) -> None:
        logger.debug("yt-dlp error: %s", msg)


def _estimate_selected_download_size(info: dict[str, Any]) -> int | None:
    requested_formats = info.get("requested_formats") or []
    if requested_formats:
        sizes = [
            int(size)
            for fmt in requested_formats
            for size in [fmt.get("filesize") or fmt.get("filesize_approx")]
            if size
        ]
        if sizes:
            return sum(sizes)

    single_size = info.get("filesize") or info.get("filesize_approx")
    return int(single_size) if single_size else None


def _format_size_for_log(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "未知"
    return f"{size_bytes / (1024 * 1024):.1f} MiB"


def _extract_selected_video_short_edge(info: dict[str, Any]) -> int | None:
    requested_formats = info.get("requested_formats") or []
    video_formats = [fmt for fmt in requested_formats if fmt.get("vcodec") != "none"]
    candidates = video_formats or [info]

    for candidate in candidates:
        width = candidate.get("width")
        height = candidate.get("height")
        if width and height:
            return min(int(width), int(height))

    return None


class DownloadAgent(BaseAgent):

    role = "视频下载专员"
    goal = "使用 yt-dlp 从多平台下载视频"
    DUBBING_SOFT_BONUS = 8.0
    KEEP_TRANSCRIPTION_MODEL_LOADED_BY_DEFAULT = True

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        model = get_text_model()
        self.video_picker = Agent(
            model=model,
            output_type=VideoPick,
            system_prompt=(download_pick_system_prompt(),),
        )
        self.font_selector = Agent(
            model=model,
            output_type=FontSelection,
            system_prompt=(
                download_font_selector_system_prompt(font_list_text=_FONT_LIST_TEXT),
            ),
        )
        self.subtitle_translation_agent = SubtitleTranslationAgent()
        self.asr_service = get_asr_service()
        self._apply_font_selection(_default_font_selection())

    async def forward(
        self,
        sources: List[VideoSource],
        output_dir: Path,
        topic: str = "",
        preselect_top_k: int = DEFAULT_PRESELECT_TOP_K,
    ) -> DownloadResult:
        if not sources:
            raise RuntimeError("没有可下载的视频源")

        try:
            total_sources = len(sources)
            top_k = max(1, min(preselect_top_k, total_sources))
            logger.info(f"候选视频总数: {total_sources}，预筛选 Top {top_k} 进入下载")

            # Step 1: 预评分，按元数据筛选 TopK
            selected_sources = self._preselect_sources(sources, topic, top_k)

            # Step 2: 下载 TopK 候选 + 转录文本（用于精细评分）
            candidates = await self._download_candidates(
                selected_sources,
                output_dir,
                stage_name=f"Top{len(selected_sources)}",
            )
            if not candidates and len(selected_sources) < total_sources:
                selected_urls = {s.url for s in selected_sources}
                fallback_sources = [s for s in sources if s.url not in selected_urls]
                logger.warning(
                    f"Top{len(selected_sources)} 下载全部失败，回退尝试剩余 {len(fallback_sources)} 个候选"
                )
                candidates = await self._download_candidates(
                    fallback_sources,
                    output_dir,
                    stage_name="Fallback",
                )
            if not candidates:
                raise RuntimeError(f"所有 {total_sources} 个视频源下载均失败")

            # Step 3: 综合打分 + LLM 评估，选出最佳视频
            best = await self._pick_best(candidates, topic)
            logger.info(f"选中最佳视频: {best.source.title[:50]}")
            for c in candidates:
                if c is not best and c.local_path:
                    path = Path(c.local_path)
                    if path.exists():
                        path.unlink(missing_ok=True)

            # Step 4: 字体选择
            await self._select_font(best.source, topic)

            # Step 5: 字幕生成（转录 → 翻译 → SRT → 烧录）
            best = await self._transcribe(best, topic)

            return best
        finally:
            self._maybe_release_asr_resources()

    def _maybe_release_asr_resources(self) -> None:
        keep_loaded_raw = os.getenv("VIDEO_POST_KEEP_TRANSCRIPTION_MODEL_LOADED", "").strip().lower()
        if not keep_loaded_raw:
            keep_loaded_raw = os.getenv("VIDEO_POST_KEEP_WHISPER_LOADED", "").strip().lower()
        if keep_loaded_raw:
            keep_loaded = keep_loaded_raw in {"1", "true", "yes", "y", "on"}
        else:
            keep_loaded = self.KEEP_TRANSCRIPTION_MODEL_LOADED_BY_DEFAULT

        if keep_loaded:
            logger.info("转录模型保持常驻（CUDA），跳过释放")
        else:
            release_asr_resources()

    async def _download_candidates(
        self,
        sources: List[VideoSource],
        output_dir: Path,
        stage_name: str,
    ) -> list[DownloadResult]:
        """下载候选并提取转录文本（用于后续细评分）。"""
        candidates: list[DownloadResult] = []
        for i, source in enumerate(sources):
            logger.info(
                f"[{stage_name}] 尝试下载 [{i + 1}/{len(sources)}]: "
                f"{source.platform.value} - {source.url[:60]}"
            )

            result = await self.step(source, output_dir)
            validation = await self.validate(result)

            if not validation.passed:
                failure_detail = result.error_message or validation.feedback
                logger.warning(f"[{stage_name}] 下载失败: {failure_detail}")
                continue

            logger.info(f"[{stage_name}] 下载成功: {result.local_path}")

            # 转录（获取字幕文本用于细评分）
            result = await self._transcribe_text_only(result)
            candidates.append(result)

        return candidates

    @staticmethod
    def _extract_topic_tokens(topic: str) -> list[str]:
        """提取话题关键词（中文/英文），用于预评分的文本相关性。"""
        raw = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", topic.lower())
        # 过滤极短 token，避免噪声词过多
        return [t for t in raw if len(t) >= 2]

    def _pre_score_source(self, source: VideoSource, topic: str) -> float:
        """
        预评分（仅用元数据，不下载）：
        - 互动数据
        - 时长合理性
        - 视频清晰度
        - 标题/描述与话题相关性
        """
        import math

        score = 0.0

        # 互动数据（0-55）
        eng = source.engagement
        if eng.likes > 0:
            score += min(math.log10(eng.likes) / 6, 1.0) * 25
        if eng.comments > 0:
            score += min(math.log10(eng.comments) / 5, 1.0) * 20
        if eng.views > 0:
            score += min(math.log10(eng.views) / 7, 1.0) * 10

        # 时长（0-25）
        duration = source.duration_seconds
        if 60 <= duration <= 300:
            score += 25
        elif 300 < duration <= 600:
            score += 18
        elif 30 <= duration < 60:
            score += 12
        else:
            score += 6

        # 视频清晰度（0-20）
        width = source.video_width or 0
        height = source.video_height or 0
        if width > 0 and height > 0:
            # 对横屏/竖屏统一用短边判档，避免 720x1280 被误判成 1280p。
            short_edge = min(width, height)
        else:
            short_edge = max(width, height)

        if short_edge >= 2160:
            score += 20
        elif short_edge >= 1440:
            score += 18
        elif short_edge >= 1080:
            score += 15
        elif short_edge >= 720:
            score += 10
        elif short_edge >= 480:
            score += 6
        elif short_edge > 0:
            score += 3

        # 话题相关性（0-20）
        topic_tokens = self._extract_topic_tokens(topic)
        if topic_tokens:
            haystack = f"{source.title} {source.description}".lower()
            matched = sum(1 for t in topic_tokens if t in haystack)
            score += min(matched / len(topic_tokens), 1.0) * 20

        return score

    def _preselect_sources(
        self,
        sources: List[VideoSource],
        topic: str,
        top_k: int,
    ) -> List[VideoSource]:
        """轻量预筛选：从候选中选出 TopK 进入下载。"""
        scored = [(self._pre_score_source(s, topic), s) for s in sources]
        scored.sort(key=lambda x: (x[0], x[1].engagement_score), reverse=True)

        logger.info(f"预评分完成（仅元数据），Top {top_k}：")
        for i, (score, source) in enumerate(scored[:top_k], 1):
            resolution = (
                f"{source.video_width}x{source.video_height}"
                if source.video_width and source.video_height
                else "未知"
            )
            logger.info(
                f"  {i}. 预分 {score:.1f} | 清晰度 {resolution} | "
                f"[{source.platform.value}] {source.title[:50]}"
            )

        return [s for _, s in scored[:top_k]]

    async def _transcribe_text_only(self, result: DownloadResult) -> DownloadResult:
        """仅提取转录文本（用于打分），不生成字幕和烧录"""
        video_path = Path(result.local_path)

        try:
            transcriber = AudioTranscriber()
            transcription = await transcriber.transcribe(video_path)
            result.transcription = transcription
            if transcription.success:
                logger.info(f"音频转录: {len(transcription.transcript)} 字符, 语言: {transcription.language}")
        except Exception as e:
            logger.warning(f"转录失败: {e}")

        return result

    @staticmethod
    def _has_usable_transcript(result: DownloadResult) -> bool:
        transcription = result.transcription
        if not transcription or not transcription.success:
            return False
        return bool(transcription.transcript and transcription.transcript.strip())

    def _score_video(self, result: DownloadResult, topic: str) -> float:
        """综合打分：转录质量 + 互动数据 + 时长合理性"""
        score = 0.0
        source = result.source

        # 转录质量（0-40 分）
        if self._has_usable_transcript(result):
            transcript_text = result.transcription.transcript.strip()
            transcript_len = len(transcript_text)
            score += min(transcript_len / 2000, 1.0) * 30
            if result.transcription.language == "zh":
                score += 10
            elif result.transcription.language in ("ja", "ko"):
                score += 5

        # 互动数据（0-30 分）
        eng = source.engagement
        # 取对数避免极端值主导
        import math
        if eng.likes > 0:
            score += min(math.log10(eng.likes) / 6, 1.0) * 15  # 1M likes = 满分
        if eng.comments > 0:
            score += min(math.log10(eng.comments) / 5, 1.0) * 10  # 100K comments = 满分
        if eng.views > 0:
            score += min(math.log10(eng.views) / 7, 1.0) * 5  # 10M views = 满分

        # 时长合理性（0-20 分）
        duration = source.duration_seconds
        if 60 <= duration <= 300:
            score += 20  # 1-5 分钟最理想
        elif 300 < duration <= 600:
            score += 15  # 5-10 分钟不错
        elif 30 <= duration < 60:
            score += 10  # 30 秒-1 分钟偏短
        else:
            score += 5  # 太短或太长(>10分钟)

        # 文件大小合理性（0-10 分）
        size_mb = result.file_size_bytes / (1024 * 1024)
        if 5 <= size_mb <= 200:
            score += 10
        elif size_mb > 200:
            score += 5

        return score

    async def _pick_best(self, candidates: list[DownloadResult], topic: str) -> DownloadResult:
        """规则打分 + LLM 评估内容质量，选出最佳视频"""
        # Step 1: 规则打分 + 可配音软优先加权
        scored = []
        for c in candidates:
            base_score = self._score_video(c, topic)
            dubbing_ready = self._has_usable_transcript(c)
            dubbing_bonus = self.DUBBING_SOFT_BONUS if dubbing_ready else 0.0
            total_score = base_score + dubbing_bonus
            scored.append((total_score, base_score, dubbing_bonus, c))
            logger.info(
                f"  综合分 {total_score:.0f} = 规则分 {base_score:.0f} + "
                f"可配音加权 {dubbing_bonus:.0f}: {c.source.title[:50]} ({c.source.platform.value})"
            )

        dubbable_count = sum(1 for c in candidates if self._has_usable_transcript(c))
        if dubbable_count > 0:
            logger.info(
                f"检测到 {dubbable_count} 个可配音候选，将使用软优先策略"
                f"（可配音候选额外 +{self.DUBBING_SOFT_BONUS:.0f} 分）"
            )
        else:
            logger.warning("候选均无有效转录，将按常规综合分选择（本次可能跳过 AI 配音）")

        # Step 2: LLM 从候选中选出最佳
        videos_desc = []
        for i, (total_score, base_score, dubbing_bonus, c) in enumerate(scored):
            transcript_preview = ""
            transcript_len = 0
            dubbing_ready = self._has_usable_transcript(c)
            if dubbing_ready:
                cleaned = c.transcription.transcript.strip()
                transcript_len = len(cleaned)
                transcript_preview = cleaned[:200]
            videos_desc.append(
                f"[{i}] 标题: {c.source.title}\n"
                f"    平台: {c.source.platform.value}, 时长: {c.source.duration_seconds}秒\n"
                f"    👍{c.source.engagement.likes} 💬{c.source.engagement.comments} 👁{c.source.engagement.views}\n"
                f"    综合分: {total_score:.0f}（规则分 {base_score:.0f} + 可配音加权 {dubbing_bonus:.0f}）\n"
                f"    可配音: {'是' if dubbing_ready else '否'}, 转录字数: {transcript_len}\n"
                f"    转录预览: {transcript_preview or '无转录'}"
            )

        prompt = download_pick_user_prompt(
            topic=topic,
            candidate_count=len(scored),
            videos_desc="\n\n".join(videos_desc),
        )

        try:
            result = await self.video_picker.run(prompt)
            pick = result.output

            idx = pick.best_index
            if 0 <= idx < len(scored):
                logger.info(
                    f"LLM 选择: [{idx}] {scored[idx][3].source.title[:50]} — {pick.reason}"
                )
                return scored[idx][3]
            else:
                logger.warning(f"LLM 返回无效索引 {idx}，回退综合分最高")
        except Exception as e:
            logger.warning(f"LLM 选择失败，回退综合分最高: {e}")

        # 回退：综合分最高
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][3]

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

    async def _select_font(self, source: VideoSource, topic: str = "") -> None:
        try:
            prompt = download_font_selector_user_prompt(
                topic=topic,
                video_title=source.title,
                video_description=source.description,
            )
            result = await self.font_selector.run(prompt)
            selection = result.output
            resolved_selection = self._validate_font_selection(selection)
            self._apply_font_selection(resolved_selection)
            logger.info(f"字体选择: {resolved_selection.font_file} — {resolved_selection.reason}")
        except Exception as e:
            self._apply_font_selection(_default_font_selection())
            logger.warning(f"字体选择失败，使用默认字体: {e}")

    async def _transcribe(self, result: DownloadResult, topic: str = "") -> DownloadResult:
        video_path = Path(result.local_path)
        output_dir = video_path.parent
        subtitled_path = output_dir / f"{video_path.stem}_subtitled{video_path.suffix}"

        has_existing_transcript = (
            result.transcription is not None
            and result.transcription.success
            and bool(result.transcription.transcript)
        )
        if has_existing_transcript:
            logger.info(
                f"复用候选阶段转录结果: {len(result.transcription.transcript)} 字符，"
                "跳过二次纯文本转录"
            )
        else:
            try:
                transcriber = AudioTranscriber()
                transcription = await transcriber.transcribe(video_path)
                result.transcription = transcription
                if transcription.success:
                    logger.info(f"转录成功: {len(transcription.transcript)} 字符")
                else:
                    logger.warning(f"转录失败: {transcription.error_message}")
            except Exception as e:
                logger.warning(f"转录过程异常（不影响下载结果）: {e}")

        try:
            subtitle_result_obj = await self._generate_and_burn_subtitles(
                video_path=video_path,
                output_path=subtitled_path,
                topic=topic,
                font_name=getattr(self, '_font_name', ''),
                font_path=getattr(self, '_font_path', None),
            )

            result.subtitle = subtitle_result_obj

            if subtitle_result_obj.success:
                result.local_path = subtitle_result_obj.video_with_subs
                logger.info(f"字幕生成并烧录成功: {subtitled_path}")
            else:
                logger.warning(f"字幕生成失败: {subtitle_result_obj.error_message}")
        except Exception as e:
            logger.warning(f"字幕生成过程异常（不影响下载结果）: {e}")

        return result

    async def _generate_and_burn_subtitles(
        self,
        video_path: Path,
        output_path: Path,
        topic: str = "",
        font_name: str = "",
        font_path: Path | None = None,
    ) -> SubtitleResult:
        try:
            logger.info(f"开始生成字幕: {video_path.name}")

            audio_path = await extract_audio_track(video_path)
            segments, detected_lang = await self._transcribe_audio(audio_path)

            if segments:
                segments = await self._assign_speakers(segments, audio_path)

            if audio_path.exists():
                audio_path.unlink(missing_ok=True)

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
            tts_segments = build_tts_segments(segments)
            generate_srt(segments, srt_path, include_tone_tags=False)
            logger.info(f"屏显 SRT 文件生成: {srt_path}")
            generate_srt(tts_segments, tts_srt_path, include_tone_tags=True)
            logger.info(f"TTS SRT 文件生成: {tts_srt_path}")

            await burn_subtitles(
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
            return SubtitleResult(success=False, error_message=str(e))

    async def _transcribe_audio(self, audio_path: Path) -> tuple[list[SubtitleSegment], str]:
        logger.info("开始音频转录并生成字幕片段...")
        transcription = await self.asr_service.transcribe_audio(audio_path)
        if not transcription.success:
            raise RuntimeError(transcription.error_message or "ASR 转录失败")

        detected_lang = transcription.language
        logger.info(f"检测到语言: {detected_lang}")
        logger.info(f"转录完成: {len(transcription.segments)} 个字幕片段")
        return [
            SubtitleSegment(
                start=segment.start,
                end=segment.end,
                text=normalize_subtitle_text(segment.text),
                speaker_id=segment.speaker_id,
                tone_tag=DEFAULT_TONE_TAG,
            )
            for segment in transcription.segments
        ], detected_lang

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
        from ..utils.tts_tags import normalize_tone_tag

        def _resolve_tone_tag(seg: SubtitleSegment) -> str:
            return normalize_tone_tag(seg.tone_tag or DEFAULT_TONE_TAG)

        normalized_source = [
            SubtitleSegment(
                start=segment.start,
                end=segment.end,
                text=normalize_subtitle_text(segment.text),
                speaker_id=segment.speaker_id,
                tone_tag=_resolve_tone_tag(segment),
            )
            for segment in segments
        ]
        if not normalized_source:
            return []

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
                translated_batch = await self.subtitle_translation_agent.forward(
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
                text=normalize_subtitle_text(segment.text),
                speaker_id=segment.speaker_id,
                tone_tag=_resolve_tone_tag(segment),
            )
            for segment in translated_segments
        ]

    def _validate_font_selection(self, selection: FontSelection) -> FontSelection:
        font_info = _CATALOG_BY_FILE.get(selection.font_file)
        if font_info is None:
            logger.warning(f"LLM 选择了未知字体: {selection.font_file}，回退默认")
            return _default_font_selection()

        font_path = FONTS_DIR / selection.font_file
        if not font_path.exists():
            logger.warning(f"字体文件不存在: {selection.font_file}，回退默认")
            return _default_font_selection()

        return selection

    def _apply_font_selection(self, selection: FontSelection) -> None:
        font_info = _CATALOG_BY_FILE.get(selection.font_file)
        if font_info is None:
            fallback = _default_font_selection()
            font_info = _CATALOG_BY_FILE[fallback.font_file]
            selection = fallback

        self._font_file = selection.font_file
        self._font_name = font_info["font_family"]
        self._font_path = FONTS_DIR / selection.font_file

    def _select_download_format(self, yt_dlp_module: Any, source: VideoSource, ydl_opts: dict[str, Any]) -> str:
        probe_opts = {
            **ydl_opts,
            "simulate": True,
            "skip_download": True,
        }

        with yt_dlp_module.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(source.url, download=False)

        selected_format = info.get("format_id") or ydl_opts["format"]
        estimated_size = _estimate_selected_download_size(info)
        selected_short_edge = _extract_selected_video_short_edge(info)
        logger.info(
            "yt-dlp 预选格式: format=%s, short_edge=%s, 预估大小=%s",
            selected_format,
            selected_short_edge or "未知",
            _format_size_for_log(estimated_size),
        )

        if selected_short_edge is not None and selected_short_edge < TARGET_DOWNLOAD_SHORT_EDGE:
            raise RuntimeError(
                "未找到不低于 1080p 的下载格式，"
                f"当前最优候选 short_edge={selected_short_edge}"
            )

        if estimated_size is not None and estimated_size > MAX_FILE_SIZE:
            raise RuntimeError(
                "没有符合大小限制的 1080p+ 格式，"
                f"最优候选 format={selected_format}, estimated={_format_size_for_log(estimated_size)}"
            )

        return selected_format

    async def _download_with_ytdlp(self, source: VideoSource, output_dir: Path) -> Path:
        import yt_dlp

        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "%(title).50s.%(ext)s")

        platform_opts = PLATFORM_OPTS.get(source.platform, {})
        format_spec = platform_opts.get("format", "best[ext=mp4]/best")
        format_sort = platform_opts.get("format_sort", DEFAULT_FORMAT_SORT)

        ydl_opts = {
            "format": format_spec,
            "format_sort": format_sort,
            "format_sort_force": True,
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4/mkv",
            "socket_timeout": 30,
            "retries": 3,
            "logger": _YtDlpLogger(),
        }

        def _sync_download(opts: dict) -> Path:
            selected_format = self._select_download_format(yt_dlp, source, opts)
            download_opts = {
                **opts,
                "format": selected_format,
            }
            download_opts.pop("format_sort", None)
            download_opts.pop("format_sort_force", None)

            with yt_dlp.YoutubeDL(download_opts) as ydl:
                info = ydl.extract_info(source.url, download=True)
                filename = ydl.prepare_filename(info)
                base = os.path.splitext(filename)[0]
                video_path = None
                for ext in ['.mp4', '.webm', '.mkv', '.avi', '.mov']:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        video_path = Path(candidate)
                        break
                if video_path is None:
                    video_path = Path(filename)
            return video_path

        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _sync_download, ydl_opts),
                timeout=DOWNLOAD_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"视频下载超时 ({DOWNLOAD_TIMEOUT}s): {source.url[:80]}")


def _default_font_selection() -> FontSelection:
    return FontSelection(
        font_file=DEFAULT_FONT_FILE,
        reason="默认回退字体",
    )
