"""
视频配音工具 — 生成中文配音并替换视频音轨

流程：
1. 提取视频音频
2. 分离人声和背景音乐 (audio-separator / RoFormer)
3. 解析 SRT 字幕，按段调用 TTS（Fish Speech / Google TTS）
4. 先保留自然语速，再只对极小残差做时长修正
5. 拼接所有配音段 + 混合背景音乐
6. 替换视频音轨
"""

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from ...shared.utils.asr.model_sources import HF_HUB_CACHE_DIR, prepare_hf_cache_env
from ....utils.logger import get_logger
from .tts import TtsSynthesisContext, TtsSynthesisRequest, TtsSynthesisResult, create_tts_service
from .tts_alignment import (
    AlignmentResult,
    TtsAligner,
    TtsTimingDecision,
    create_tts_aligner,
)
from .tts_tags import normalize_tone_tag

logger = get_logger(__name__)

# 项目路径与统一缓存路径
PROJECT_ROOT = Path(__file__).resolve().parents[4]
PROJECT_CACHE = PROJECT_ROOT / ".cache"
MODELSCOPE_CACHE_DIR = PROJECT_CACHE / "modelscope"
TORCH_CACHE_DIR = PROJECT_CACHE / "torch"
AUDIO_SEPARATOR_MODEL_DIR = PROJECT_CACHE / "audio-separator" / "models"

# 人声分离模型（自动下载）
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
MIN_NATURAL_ATEMPO = 0.95
MAX_NATURAL_ATEMPO = 1.05
MIN_SOFT_STRETCH_RATIO = 0.97
MAX_SOFT_STRETCH_RATIO = 1.03
MAX_CARRYOVER_SECONDS = 0.30
MAX_CARRYOVER_RATIO = 0.08


def _prepare_model_cache_env() -> None:
    """准备 TTS 运行时缓存环境，默认尊重用户级 Hugging Face 缓存设置。"""
    prepare_hf_cache_env()
    HF_HUB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MODELSCOPE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_SEPARATOR_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for key, value in _cache_env_vars().items():
        os.environ.setdefault(key, value)


def _cache_env_vars() -> dict[str, str]:
    return {
        "MODELSCOPE_CACHE": str(MODELSCOPE_CACHE_DIR),
        "TORCH_HOME": str(TORCH_CACHE_DIR),
    }


@lru_cache(maxsize=1)
def _get_tts_aligner() -> TtsAligner:
    return create_tts_aligner()


async def dub_video(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    work_dir: Path | None = None,
    bg_volume: float = 0.6,
    voice: str = "",
) -> Path:
    """
    完整视频配音流程

    Args:
        video_path: 原视频路径（带外语音频）
        srt_path: 已翻译的中文 SRT 字幕文件
        output_path: 输出配音视频路径
        work_dir: 工作目录（临时文件），None 则自动创建
        bg_volume: 背景音乐音量（0.0-1.0）

    Returns:
        输出视频路径
    """
    if not voice:
        voice = os.getenv("S2CPP_TTS_VOICE", "").strip()

    _prepare_model_cache_env()

    cleanup = work_dir is None
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="dub_"))
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: 提取音频
        logger.info("Step 1: 提取视频音频...")
        original_audio = work_dir / "original.wav"
        await _extract_audio(video_path, original_audio)

        # Step 2: 分离人声和背景音乐
        logger.info("Step 2: 分离人声和背景音乐...")
        _vocals_path, bgm_path = await _separate_vocals(original_audio, work_dir)

        # Step 3: 解析 SRT + 逐段生成配音
        logger.info("Step 3: 解析字幕并生成配音...")
        segments = parse_srt(srt_path)
        dubbed_segments = await _generate_dubbed_segments(
            segments=segments,
            work_dir=work_dir,
            reference_audio_path=original_audio,
            voice=voice,
        )

        # Step 4: 拼接配音段为完整音轨
        logger.info("Step 4: 拼接配音音轨...")
        video_duration = await _get_duration(video_path)
        dubbed_audio = work_dir / "dubbed_full.wav"
        await _concat_segments_with_silence(
            dubbed_segments, dubbed_audio, video_duration
        )

        # Step 5: 混合配音 + 背景音乐
        logger.info("Step 5: 混合配音与背景音乐...")
        mixed_audio = work_dir / "mixed.wav"
        if bgm_path is not None and bgm_path.exists():
            await _mix_audio(dubbed_audio, bgm_path, mixed_audio, bg_volume=bg_volume)
        else:
            shutil.copy2(dubbed_audio, mixed_audio)
            logger.warning("未检测到可用背景音乐，输出为纯中文配音音轨")

        # Step 6: 替换视频音轨
        logger.info("Step 6: 替换视频音轨...")
        await _replace_audio(video_path, mixed_audio, output_path)

        logger.info(f"配音完成: {output_path}")
        return output_path

    finally:
        if cleanup:
            shutil.rmtree(work_dir, ignore_errors=True)


# ─── SRT 解析 ────────────────────────────────────────────────

class SrtSegment:
    def __init__(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        speaker_id: int = 0,
        tone_tag: str = "",
    ):
        self.index = index
        self.start = start
        self.end = end
        self.text = text
        self.speaker_id = speaker_id
        self.tone_tag = tone_tag

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_srt(srt_path: Path) -> list[SrtSegment]:
    """解析 SRT 文件为段列表"""
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    segments = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1].strip(),
        )
        if not time_match:
            continue

        start = _srt_time_to_seconds(time_match.group(1))
        end = _srt_time_to_seconds(time_match.group(2))
        text = " ".join(lines[2:]).strip()
        # 去掉 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)

        speaker_id = 0
        sp_match = re.match(r'\[S(\d+)\]\s*', text)
        if sp_match:
            speaker_id = int(sp_match.group(1))
            text = text[sp_match.end():]

        tone_tag = ""
        tone_match = re.match(r"\[([^\]]+)\]\s*", text)
        if tone_match:
            tone_tag = normalize_tone_tag(tone_match.group(1))
            text = text[tone_match.end():].strip()

        if text:
            segments.append(
                SrtSegment(
                    index,
                    start,
                    end,
                    text,
                    speaker_id=speaker_id,
                    tone_tag=tone_tag,
                )
            )

    return segments


def _srt_time_to_seconds(time_str: str) -> float:
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


# ─── 音频处理 ────────────────────────────────────────────────

async def _extract_audio(video_path: Path, output_path: Path) -> None:
    """从视频提取音频为 WAV"""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"音频提取失败: {stderr.decode()[-300:]}")


async def _separate_vocals(audio_path: Path, output_dir: Path) -> tuple[Path, Path | None]:
    """分离人声和背景音乐"""
    loop = asyncio.get_running_loop()

    def _sync_separate():
        _prepare_model_cache_env()
        try:
            from audio_separator.separator import Separator
        except Exception as e:
            logger.warning(f"未安装或无法加载 audio_separator，跳过分离: {e}")
            return None

        separator = Separator(
            output_dir=str(output_dir),
            output_format="WAV",
            sample_rate=44100,
            model_file_dir=str(AUDIO_SEPARATOR_MODEL_DIR),
        )
        separator.load_model(model_filename=SEPARATOR_MODEL)
        output_files = separator.separate(str(audio_path))
        return output_files

    output_files = await loop.run_in_executor(None, _sync_separate)
    if not output_files:
        logger.warning("人声分离不可用，将不保留背景音乐，仅输出配音音轨")
        return audio_path, None

    resolved_files: list[Path] = []
    for file_path in output_files:
        path = Path(file_path)
        if not path.is_absolute():
            path = output_dir / path
        resolved_files.append(path)

    vocals: Path | None = None
    instrumental: Path | None = None

    # 优先根据文件名关键字识别，避免依赖第三方库返回顺序。
    for path in resolved_files:
        name = path.name.lower()
        if vocals is None and ("(vocals)" in name or "vocal" in name):
            vocals = path
        elif instrumental is None and ("(instrumental)" in name or "instrumental" in name):
            instrumental = path

    # 回退到固定顺序（某些版本可能只返回两个无关键词文件名）。
    if vocals is None and len(resolved_files) >= 1:
        vocals = resolved_files[0]
    if instrumental is None and len(resolved_files) >= 2:
        instrumental = resolved_files[1]

    if vocals is None or not vocals.exists():
        logger.warning(f"人声分离失败: 未找到人声音轨文件，返回结果={output_files}")
        return audio_path, None
    if instrumental is None or not instrumental.exists():
        logger.warning(f"人声分离失败: 未找到伴奏音轨文件，返回结果={output_files}")
        return vocals, None

    logger.info(f"分离完成: 人声={vocals.name}, 背景={instrumental.name}")
    return vocals, instrumental


# ─── TTS 配音生成 ───────────────────────────────────────────

def _segment_to_tts_request(segment: SrtSegment, voice: str = "") -> TtsSynthesisRequest:
    return TtsSynthesisRequest(
        segment_index=segment.index,
        text=segment.text,
        language="zh",
        voice=voice,
        tone_tag=segment.tone_tag,
        speaker_id=segment.speaker_id,
        target_start=segment.start,
        target_end=segment.end,
        target_duration_seconds=segment.duration,
    )


def _request_to_segment(request: TtsSynthesisRequest) -> SrtSegment:
    return SrtSegment(
        index=request.segment_index,
        start=request.target_start,
        end=request.target_end,
        text=request.text,
        speaker_id=request.speaker_id,
        tone_tag=request.tone_tag,
    )


def _display_tts_provider_name(provider_name: str) -> str:
    if provider_name == "s2cpp":
        return "s2.cpp"
    if provider_name == "google":
        return "Google"
    if provider_name == "fish":
        return "Fish"
    return provider_name


async def _generate_dubbed_segments(
    segments: list[SrtSegment],
    work_dir: Path,
    reference_audio_path: Path,
    voice: str = "",
) -> list[tuple[SrtSegment, Path]]:
    """根据配置选择 TTS 后端，生成逐段配音并尽量保留自然语速。"""
    if not segments:
        raise RuntimeError("字幕为空，无法生成配音")

    requests = [_segment_to_tts_request(segment=segment, voice=voice) for segment in segments]
    service = create_tts_service()
    logger.info("TTS Provider: %s", service.provider_name)
    batch_result = await service.synthesize_many(
        requests=requests,
        context=TtsSynthesisContext(
            work_dir=work_dir,
            reference_audio_path=reference_audio_path,
            voice=voice,
        ),
    )
    effective_segments = [_request_to_segment(request) for request in batch_result.requests]
    empty_error = f"{_display_tts_provider_name(batch_result.provider_name)} TTS 未生成任何可用配音段"
    return await _postprocess_dubbed_segments(
        success_map=batch_result.success_map,
        segments=effective_segments,
        work_dir=work_dir,
        empty_error=empty_error,
    )


async def _postprocess_dubbed_segments(
    success_map: dict[int, TtsSynthesisResult],
    segments: list[SrtSegment],
    work_dir: Path,
    empty_error: str,
) -> list[tuple[SrtSegment, Path]]:
    results: list[tuple[SrtSegment, Path]] = []
    aligner = _get_tts_aligner()
    indexed_items: list[tuple[int, SrtSegment, TtsSynthesisResult, TtsSynthesisRequest]] = []
    for i, seg in enumerate(segments):
        synthesis = success_map.get(i)
        if synthesis is None or not synthesis.audio_path.exists():
            logger.warning(f"段 {i} 配音生成失败，跳过")
            continue

        request = TtsSynthesisRequest(
            segment_index=seg.index,
            text=seg.text,
            voice="",
            tone_tag=seg.tone_tag,
            language="zh",
            speaker_id=seg.speaker_id,
            target_start=seg.start,
            target_end=seg.end,
            target_duration_seconds=seg.duration,
        )
        indexed_items.append((i, seg, synthesis, request))

    alignment_results: list[AlignmentResult] = await aligner.align_many(
        [item[2] for item in indexed_items],
        [item[3] for item in indexed_items],
    )

    for (i, seg, synthesis, request), alignment in zip(indexed_items, alignment_results):
        final_path = work_dir / f"seg_{i:04d}.wav"
        decision = await _finalize_synthesized_segment(
            synthesis=synthesis,
            request=request,
            output_path=final_path,
            alignment=alignment,
        )
        logger.info(
            "配音段 %s 时序策略: provider=%s strategy=%s raw=%.3fs target=%.3fs final=%.3fs "
            "stretch=%.3f carryover=%.3fs aligner=%s",
            i,
            synthesis.provider_name or "<unknown>",
            decision.strategy_used,
            synthesis.raw_duration_seconds,
            seg.duration,
            decision.final_duration_seconds,
            decision.stretch_ratio,
            decision.carryover_seconds,
            decision.aligner_used or "<none>",
        )
        results.append((seg, final_path))

    if not results:
        raise RuntimeError(empty_error)
    return results


def _resolve_carryover_limit(target_seconds: float) -> float:
    return min(MAX_CARRYOVER_SECONDS, max(target_seconds, 0.0) * MAX_CARRYOVER_RATIO)


def _resolve_tempo_filter(current_seconds: float, target_seconds: float) -> str | None:
    if current_seconds <= 0 or target_seconds <= 0:
        return None

    tempo = current_seconds / target_seconds
    clamped_tempo = min(max(tempo, MIN_NATURAL_ATEMPO), MAX_NATURAL_ATEMPO)
    return f"atempo={clamped_tempo:.6f}"


@lru_cache(maxsize=1)
def _ffmpeg_supports_rubberband() -> bool:
    try:
        completed = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    output = f"{completed.stdout}\n{completed.stderr}"
    return " rubberband " in output or "\nrubberband" in output


def _resolve_time_stretch_filter(current_seconds: float, target_seconds: float) -> tuple[str | None, str]:
    tempo_filter = _resolve_tempo_filter(current_seconds, target_seconds)
    if tempo_filter is None:
        return None, "copy"

    tempo = current_seconds / target_seconds
    if _ffmpeg_supports_rubberband():
        return (
            "rubberband="
            f"tempo={tempo:.6f}:transients=smooth:formant=preserved:pitchq=quality",
            "rubberband",
        )
    return tempo_filter, "atempo"


def _build_timing_decision(
    current_seconds: float,
    target_seconds: float,
) -> TtsTimingDecision:
    current = max(current_seconds, 0.0)
    target = max(target_seconds, 0.0)
    if current <= 0 or target <= 0:
        return TtsTimingDecision(
            strategy_used="copy",
            stretch_ratio=1.0,
            carryover_seconds=0.0,
            target_duration_seconds=target,
            final_duration_seconds=current,
        )

    if current <= target:
        return TtsTimingDecision(
            strategy_used="pad",
            stretch_ratio=1.0,
            carryover_seconds=0.0,
            target_duration_seconds=target,
            final_duration_seconds=current,
        )

    carryover_seconds = current - target
    carryover_limit = _resolve_carryover_limit(target)
    stretch_ratio = current / target

    if carryover_seconds <= carryover_limit + 1e-6:
        return TtsTimingDecision(
            strategy_used="carryover",
            stretch_ratio=1.0,
            carryover_seconds=carryover_seconds,
            target_duration_seconds=target,
            final_duration_seconds=current,
        )

    if MIN_SOFT_STRETCH_RATIO <= stretch_ratio <= MAX_SOFT_STRETCH_RATIO:
        return TtsTimingDecision(
            strategy_used="stretch",
            stretch_ratio=stretch_ratio,
            carryover_seconds=0.0,
            target_duration_seconds=target,
            final_duration_seconds=target,
        )

    return TtsTimingDecision(
        strategy_used="carryover_hard",
        stretch_ratio=1.0,
        carryover_seconds=carryover_seconds,
        target_duration_seconds=target,
        final_duration_seconds=current,
        used_fallback=stretch_ratio > MAX_NATURAL_ATEMPO,
    )


def _plan_concat_silence(
    segments: list[tuple[SrtSegment, float]],
    total_duration: float,
) -> tuple[list[float], float]:
    silences: list[float] = []
    cursor = 0.0

    for seg, audio_duration in segments:
        desired_start = max(seg.start, 0.0)
        actual_start = max(desired_start, cursor)
        silences.append(max(0.0, actual_start - cursor))
        cursor = actual_start + max(audio_duration, 0.0)

    tail_gap = max(total_duration - cursor, 0.0)
    return silences, tail_gap


async def _trim_segment_silence(input_path: Path, output_path: Path) -> Path:
    """保守裁掉 TTS 段首尾静音，减少无意义的时长拉伸。"""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af",
        "silenceremove="
        "start_periods=1:start_silence=0.03:start_threshold=-45dB:"
        "stop_periods=1:stop_silence=0.05:stop_threshold=-45dB",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await proc.communicate()
    if proc.returncode != 0 or not output_path.exists():
        shutil.copy2(input_path, output_path)
    return output_path


async def _trim_audio_to_range(
    input_path: Path,
    output_path: Path,
    *,
    start_seconds: float,
    end_seconds: float,
) -> Path:
    start = max(start_seconds, 0.0)
    end = max(end_seconds, start + 0.01)
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", f"atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await proc.communicate()
    if proc.returncode != 0 or not output_path.exists():
        shutil.copy2(input_path, output_path)
    return output_path


def _resolve_aligned_range(
    alignment: AlignmentResult,
    fallback_duration: float,
) -> tuple[float, float] | None:
    if not alignment.tokens:
        return None

    start = max(alignment.tokens[0].start - 0.02, 0.0)
    end = max(alignment.tokens[-1].end + 0.03, start + 0.01)
    if fallback_duration > 0:
        end = min(end, fallback_duration)
    return start, end


async def _finalize_synthesized_segment(
    synthesis: TtsSynthesisResult,
    request: TtsSynthesisRequest,
    output_path: Path,
    alignment: AlignmentResult,
) -> TtsTimingDecision:
    source_duration = await _get_duration(synthesis.audio_path)
    trimmed_path = output_path.with_name(f"{output_path.stem}_trimmed{output_path.suffix}")
    aligned_range = _resolve_aligned_range(alignment, source_duration)
    if aligned_range is not None:
        trimmed_path = await _trim_audio_to_range(
            synthesis.audio_path,
            trimmed_path,
            start_seconds=aligned_range[0],
            end_seconds=aligned_range[1],
        )
    else:
        trimmed_path = await _trim_segment_silence(synthesis.audio_path, trimmed_path)
    raw_duration = await _get_duration(trimmed_path)

    synthesis.raw_duration_seconds = raw_duration
    decision = _build_timing_decision(raw_duration, request.target_duration_seconds)
    decision.aligner_used = alignment.aligner_used
    decision.used_fallback = alignment.used_fallback
    if alignment.tokens:
        synthesis.provider_metadata["aligned_token_count"] = len(alignment.tokens)

    if decision.strategy_used == "stretch":
        await _adjust_duration(trimmed_path, output_path, request.target_duration_seconds)
    else:
        shutil.copy2(trimmed_path, output_path)

    final_duration = await _get_duration(output_path)
    decision.final_duration_seconds = final_duration
    return decision


async def _adjust_duration(input_path: Path, output_path: Path, target_seconds: float) -> None:
    """仅在极小残差时做时长修正，默认优先保留自然语速。"""
    current = await _get_duration(input_path)
    decision = _build_timing_decision(current, target_seconds)
    if decision.strategy_used != "stretch":
        shutil.copy2(input_path, output_path)
        return

    tempo_filter, strategy = _resolve_time_stretch_filter(current, target_seconds)
    if tempo_filter is None:
        shutil.copy2(input_path, output_path)
        return

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter:a", tempo_filter,
        "-acodec", "pcm_s16le",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await proc.communicate()

    if not output_path.exists():
        shutil.copy2(input_path, output_path)
        return

    logger.info(
        "配音段做极小幅时长修正: strategy=%s raw=%.3fs target=%.3fs",
        strategy,
        current,
        target_seconds,
    )


async def _concat_segments_with_silence(
    segments: list[tuple[SrtSegment, Path]],
    output_path: Path,
    total_duration: float,
) -> None:
    """按字幕时间戳拼接配音段，允许超长段顺延，避免过短段提前开口。"""
    if not segments:
        raise RuntimeError("没有可用的配音段")

    # 生成静音填充 + 配音段的 filter_complex
    inputs = []
    filter_parts = []

    for i, (seg, audio_path) in enumerate(segments):
        inputs.extend(["-i", str(audio_path)])

    audio_durations = await asyncio.gather(*[_get_duration(audio_path) for _, audio_path in segments])
    silence_durations, tail_gap = _plan_concat_silence(
        [(seg, duration) for (seg, _), duration in zip(segments, audio_durations)],
        total_duration,
    )

    # 构建 filter_complex：每段最早不早于原字幕开始，若前段超长则顺延
    concat_inputs = []
    for i, silence_duration in enumerate(silence_durations):
        if silence_duration > 0.01:
            filter_parts.append(
                f"aevalsrc=0:d={silence_duration:.3f}:s=44100:c=mono[sil{i}]"
            )
            concat_inputs.append(f"[sil{i}]")
        concat_inputs.append(f"[{i}:a]")

    # 尾部静音（如果配音比视频短）
    if tail_gap > 0.5:
        filter_parts.append(
            f"aevalsrc=0:d={tail_gap:.3f}:s=44100:c=mono[siltail]"
        )
        concat_inputs.append("[siltail]")

    n_concat = len(concat_inputs)
    concat_str = "".join(concat_inputs)
    filter_parts.append(f"{concat_str}concat=n={n_concat}:v=0:a=1[out]")

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-acodec", "pcm_s16le", "-ar", "44100",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"音频拼接失败: {stderr.decode()[-500:]}")


async def _mix_audio(
    vocals_path: Path,
    bgm_path: Path,
    output_path: Path,
    vocal_volume: float = 1.0,
    bg_volume: float = 0.6,
) -> None:
    """混合配音和背景音乐"""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-i", str(bgm_path),
        "-filter_complex",
        f"[0:a]volume={vocal_volume}[v];"
        f"[1:a]volume={bg_volume}[b];"
        f"[v][b]amix=inputs=2:duration=longest:dropout_transition=0[out]",
        "-map", "[out]",
        "-acodec", "pcm_s16le", "-ar", "44100",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"音频混合失败: {stderr.decode()[-500:]}")


async def _replace_audio(video_path: Path, audio_path: Path, output_path: Path) -> None:
    """替换视频音轨"""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-shortest",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"音轨替换失败: {stderr.decode()[-500:]}")


async def _get_duration(file_path: Path) -> float:
    """获取音频/视频时长"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip())
