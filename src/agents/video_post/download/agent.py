import asyncio
import os
import re
from pathlib import Path
from typing import Any, List

import logfire

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoSource, DownloadResult, Platform
from ....utils.logger import get_logger
from ....utils.subtitle_generator import WhisperTranscriber, WhisperSubtitleGenerator, pick_subtitle_style, release_whisper_model
from ....utils.font_selector import FontSelectorAgent, get_font_info, get_fonts_dir

logger = get_logger(__name__)

BEST_QUALITY_FORMAT = "bestvideo*+bestaudio/best"

PLATFORM_OPTS = {
    Platform.YOUTUBE: {
        "format": BEST_QUALITY_FORMAT,
    },
    Platform.X: {
        "format": BEST_QUALITY_FORMAT,
    },
    Platform.INSTAGRAM: {
        "format": BEST_QUALITY_FORMAT,
    },
    Platform.FACEBOOK: {
        "format": BEST_QUALITY_FORMAT,
    },
    Platform.TIKTOK: {
        "format": BEST_QUALITY_FORMAT,
    },
}

MIN_FILE_SIZE = 100 * 1024  # 100KB
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
DOWNLOAD_TIMEOUT = 1200  # 20 minutes
DEFAULT_PRESELECT_TOP_K = 3


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
        topic: str = "",
        preselect_top_k: int = DEFAULT_PRESELECT_TOP_K,
    ) -> DownloadResult:
        self._topic = topic

        if not sources:
            raise RuntimeError("没有可下载的视频源")

        total_sources = len(sources)
        top_k = max(1, min(preselect_top_k, total_sources))
        logger.info(f"候选视频总数: {total_sources}，预筛选 Top {top_k} 进入下载")

        # Step 1: 先做轻量预评分，避免下载全部候选
        selected_sources = self._preselect_sources(sources, topic, top_k)

        # Step 2: 仅下载 TopK，并做转录用于精细评分
        candidates = await self._download_candidates(
            selected_sources,
            output_dir,
            stage_name=f"Top{len(selected_sources)}",
        )

        # 回退：若 TopK 全部失败，再尝试其余候选，避免整批失败
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

        # Step 3: 综合打分 + LLM 评估，选最佳视频
        best = await self._pick_best(candidates, topic)
        logger.info(f"选中最佳视频: {best.source.title[:50]}")

        # Step 4: 只对选中的视频做字体选择 + 字幕烧录
        await self._select_font(best.source)
        best = await self._transcribe(best)
        release_whisper_model()

        # 清理未选中的视频文件
        for c in candidates:
            if c is not best and c.local_path:
                path = Path(c.local_path)
                if path.exists():
                    path.unlink(missing_ok=True)

        return best

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
                logger.warning(f"[{stage_name}] 下载失败: {result.error_message}")
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

        ytdlp_srt = self._find_ytdlp_subtitle(video_path)
        if ytdlp_srt:
            try:
                transcript_text = self._parse_srt_text(ytdlp_srt)
                from ..schemas import TranscriptionResult
                result.transcription = TranscriptionResult(
                    success=True, transcript=transcript_text, language="zh",
                )
                logger.info(f"SRT 转录: {len(transcript_text)} 字符")
                return result
            except Exception as e:
                logger.warning(f"SRT 解析失败: {e}")

        try:
            transcriber = WhisperTranscriber()
            transcription = await transcriber.transcribe(video_path)
            result.transcription = transcription
            if transcription.success:
                logger.info(f"Whisper 转录: {len(transcription.transcript)} 字符, 语言: {transcription.language}")
        except Exception as e:
            logger.warning(f"转录失败: {e}")

        return result

    def _score_video(self, result: DownloadResult, topic: str) -> float:
        """综合打分：转录质量 + 互动数据 + 时长合理性"""
        score = 0.0
        source = result.source

        # 转录质量（0-40 分）
        if result.transcription and result.transcription.success:
            transcript_len = len(result.transcription.transcript)
            # 转录越长说明内容越丰富，上限 2000 字符得满分
            score += min(transcript_len / 2000, 1.0) * 30
            # 中文内容加分（目标平台是小红书）
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
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent
        from ....utils.providers import get_text_model

        # Step 1: 规则打分
        scored = [(self._score_video(c, topic), c) for c in candidates]
        for s, c in scored:
            logger.info(f"  规则分 {s:.0f}: {c.source.title[:50]} ({c.source.platform.value})")

        # Step 2: LLM 从候选中选出最佳
        class VideoPick(BaseModel):
            best_index: int = Field(description="最佳视频的序号（从 0 开始）")
            reason: str = Field(description="选择理由")

        videos_desc = []
        for i, (rule_score, c) in enumerate(scored):
            transcript_preview = ""
            if c.transcription and c.transcription.success:
                transcript_preview = c.transcription.transcript[:200]
            videos_desc.append(
                f"[{i}] 标题: {c.source.title}\n"
                f"    平台: {c.source.platform.value}, 时长: {c.source.duration_seconds}秒\n"
                f"    👍{c.source.engagement.likes} 💬{c.source.engagement.comments} 👁{c.source.engagement.views}\n"
                f"    规则分: {rule_score:.0f}\n"
                f"    转录预览: {transcript_preview or '无转录'}"
            )

        prompt = (
            f"话题: {topic}\n\n"
            f"以下是 {len(scored)} 个候选视频，请选出最适合在小红书发布的一个。\n"
            f"考虑因素：内容丰富度、信息价值、小红书用户兴趣匹配度、转录质量。\n\n"
            + "\n\n".join(videos_desc)
        )

        try:
            picker = Agent(
                model=get_text_model(),
                output_type=VideoPick,
                system_prompt="你是小红书内容选品专家。从候选视频中选出最适合发布的一个。优先选择内容完整、信息丰富、适合中国年轻用户的视频。",
            )
            result = await picker.run(prompt)
            pick = result.output

            idx = pick.best_index
            if 0 <= idx < len(scored):
                logger.info(f"LLM 选择: [{idx}] {scored[idx][1].source.title[:50]} — {pick.reason}")
                return scored[idx][1]
            else:
                logger.warning(f"LLM 返回无效索引 {idx}，回退规则分最高")
        except Exception as e:
            logger.warning(f"LLM 选择失败，回退规则分最高: {e}")

        # 回退：规则分最高
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

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

    async def _select_font(self, source: VideoSource) -> None:
        """使用 LLM Agent 根据视频内容选择最佳字幕字体"""
        try:
            selector = FontSelectorAgent()
            selection = await selector.select_font(
                topic=getattr(self, '_topic', ''),
                video_title=source.title,
                video_description=source.description,
            )
            self._font_file = selection.font_file
            logger.info(f"字体选择: {selection.font_file} — {selection.reason}")
        except Exception as e:
            self._font_file = ""
            logger.warning(f"字体选择失败，使用默认字体: {e}")

    async def _transcribe(self, result: DownloadResult) -> DownloadResult:
        video_path = Path(result.local_path)
        output_dir = video_path.parent
        subtitled_path = output_dir / f"{video_path.stem}_subtitled{video_path.suffix}"

        # 优先检查 yt-dlp 下载的字幕 — 有则跳过 Whisper
        ytdlp_srt = self._find_ytdlp_subtitle(video_path)

        if ytdlp_srt:
            logger.info(f"发现 yt-dlp 字幕文件: {ytdlp_srt.name}，跳过 Whisper 转录")

            # 从 SRT 解析文本作为 transcript
            try:
                transcript_text = self._parse_srt_text(ytdlp_srt)
                from ..schemas import TranscriptionResult
                result.transcription = TranscriptionResult(
                    success=True,
                    transcript=transcript_text,
                    language="zh",
                )
                logger.info(f"SRT 解析转录成功: {len(transcript_text)} 字符")
            except Exception as e:
                logger.warning(f"SRT 解析失败，回退到 Whisper: {e}")
                ytdlp_srt = None  # 回退到下面的 Whisper 分支

            if ytdlp_srt:
                # 烧录字幕
                try:
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
                    logger.info(f"平台字幕烧录成功: {subtitled_path}")
                except Exception as e:
                    logger.warning(f"字幕烧录异常（不影响下载结果）: {e}")
                return result

        # 无 yt-dlp 字幕 → Whisper 转录
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
                transcriber = WhisperTranscriber()
                transcription = await transcriber.transcribe(video_path)
                result.transcription = transcription
                if transcription.success:
                    logger.info(f"Whisper 转录成功: {len(transcription.transcript)} 字符")
                else:
                    logger.warning(f"Whisper 转录失败: {transcription.error_message}")
            except Exception as e:
                logger.warning(f"转录过程异常（不影响下载结果）: {e}")

        # Whisper 字幕生成 + 烧录
        try:
            subtitle_gen = WhisperSubtitleGenerator()
            subtitle_result_obj = await subtitle_gen.generate_and_burn(
                video_path=video_path,
                output_path=subtitled_path,
                target_language="zh",
                topic=getattr(self, '_topic', ''),
                font_file=getattr(self, '_font_file', ''),
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

    @staticmethod
    def _parse_srt_text(srt_path: Path) -> str:
        """从 SRT/VTT 文件中提取纯文本"""
        import re
        content = srt_path.read_text(encoding="utf-8", errors="replace")
        # 去掉序号行、时间码行、VTT 头部，只保留文本
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.match(r"^\d+$", line):
                continue
            if re.match(r"[\d:,.]+ --> [\d:,.]+" , line):
                continue
            if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            # 去掉 HTML 标签（如 <c>）
            line = re.sub(r"<[^>]+>", "", line)
            if line:
                lines.append(line)
        return " ".join(lines)

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
        """将已有字幕文件烧录到视频中（使用临时目录 + cwd 规避 ffmpeg 路径转义问题）"""
        import shutil
        import subprocess
        import tempfile

        style = pick_subtitle_style(getattr(self, '_topic', ''))
        font_file = getattr(self, '_font_file', '')
        font_info = get_font_info(font_file) if font_file else None
        font_name = font_info["font_family"] if font_info else "Microsoft YaHei"

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

            sub_filter = f"subtitles=sub.srt:force_style='FontName={font_name},FontSize=18,Bold=1,PrimaryColour={style['PrimaryColour']},OutlineColour={style['OutlineColour']},BackColour=&H80000000,Outline=2,Shadow=1,BorderStyle=1,MarginV=30'"
            cmd = [
                "ffmpeg", "-hwaccel", "cuda", "-i", str(video_path),
                "-vf", sub_filter,
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
                "-c:a", "copy",
                "-y", str(output_path),
            ]

            logger.info(f"烧录字幕到视频（字体: {font_name}）...")
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
            "logger": _YtDlpLogger(),
        }

        def _sync_download(opts: dict) -> Path:
            with yt_dlp.YoutubeDL(opts) as ydl:
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

            if source.platform == Platform.YOUTUBE:
                try:
                    sub_opts = {
                        "outtmpl": output_template,
                        "quiet": True,
                        "no_warnings": True,
                        "skip_download": True,
                        "writesubtitles": True,
                        "writeautomaticsub": True,
                        "subtitleslangs": ["zh-Hans", "zh-Hant", "zh", "en"],
                        "subtitlesformat": "srt",
                        "socket_timeout": 15,
                        "logger": _YtDlpLogger(),
                    }
                    with yt_dlp.YoutubeDL(sub_opts) as ydl:
                        ydl.extract_info(source.url, download=True)
                    logger.info("字幕下载成功")
                except Exception as e:
                    logger.warning(f"字幕下载失败（不影响视频下载）: {e}")

            return video_path

        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _sync_download, ydl_opts),
                timeout=DOWNLOAD_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"视频下载超时 ({DOWNLOAD_TIMEOUT}s): {source.url[:80]}")
