"""
视频配音工具 — 使用 IndexTTS-2 克隆原视频音色生成中文配音

流程：
1. 提取视频音频
2. 分离人声和背景音乐 (audio-separator / RoFormer)
3. 从人声中截取参考音频片段 (5-15 秒)
4. 解析 SRT 字幕，按段生成中文配音 (IndexTTS-2)
5. 用 ffmpeg atempo 调整每段配音时长匹配字幕时间窗
6. 拼接所有配音段 + 混合背景音乐
7. 替换视频音轨
"""

import asyncio
import re
import subprocess
import tempfile
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)

# IndexTTS-2 模型路径
INDEXTTS_DIR = Path(__file__).parent.parent.parent / "submodules" / "index-tts"
INDEXTTS_CHECKPOINTS = INDEXTTS_DIR / "checkpoints"

# 人声分离模型（自动下载）
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"


async def dub_video(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    work_dir: Path | None = None,
    bg_volume: float = 0.6,
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
    import shutil

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
        vocals_path, bgm_path = await _separate_vocals(original_audio, work_dir)

        # Step 3: 截取参考音频（用于声音克隆）
        logger.info("Step 3: 截取参考音频...")
        ref_audio = work_dir / "ref_voice.wav"
        await _extract_reference_voice(vocals_path, ref_audio)

        # Step 4: 解析 SRT + 逐段生成配音
        logger.info("Step 4: 解析字幕并生成配音...")
        segments = parse_srt(srt_path)
        dubbed_segments = await _generate_dubbed_segments(
            segments, ref_audio, work_dir
        )

        # Step 5: 拼接配音段为完整音轨
        logger.info("Step 5: 拼接配音音轨...")
        video_duration = await _get_duration(video_path)
        dubbed_audio = work_dir / "dubbed_full.wav"
        await _concat_segments_with_silence(
            dubbed_segments, dubbed_audio, video_duration
        )

        # Step 6: 混合配音 + 背景音乐
        logger.info("Step 6: 混合配音与背景音乐...")
        mixed_audio = work_dir / "mixed.wav"
        await _mix_audio(dubbed_audio, bgm_path, mixed_audio, bg_volume=bg_volume)

        # Step 7: 替换视频音轨
        logger.info("Step 7: 替换视频音轨...")
        await _replace_audio(video_path, mixed_audio, output_path)

        logger.info(f"配音完成: {output_path}")
        return output_path

    finally:
        if cleanup:
            shutil.rmtree(work_dir, ignore_errors=True)


# ─── SRT 解析 ────────────────────────────────────────────────

class SrtSegment:
    def __init__(self, index: int, start: float, end: float, text: str):
        self.index = index
        self.start = start
        self.end = end
        self.text = text

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

        if text:
            segments.append(SrtSegment(index, start, end, text))

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


async def _separate_vocals(audio_path: Path, output_dir: Path) -> tuple[Path, Path]:
    """分离人声和背景音乐"""
    loop = asyncio.get_running_loop()

    def _sync_separate():
        from audio_separator.separator import Separator

        separator = Separator(
            output_dir=str(output_dir),
            output_format="WAV",
            sample_rate=44100,
        )
        separator.load_model(model_filename=SEPARATOR_MODEL)
        output_files = separator.separate(str(audio_path))
        return output_files

    output_files = await loop.run_in_executor(None, _sync_separate)
    if not output_files:
        raise RuntimeError("人声分离失败: 未返回任何输出文件")

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
        raise RuntimeError(
            f"人声分离失败: 未找到人声音轨文件，返回结果={output_files}"
        )
    if instrumental is None or not instrumental.exists():
        raise RuntimeError(
            f"人声分离失败: 未找到伴奏音轨文件，返回结果={output_files}"
        )

    logger.info(f"分离完成: 人声={vocals.name}, 背景={instrumental.name}")
    return vocals, instrumental


async def _extract_reference_voice(vocals_path: Path, ref_path: Path, duration: float = 10.0) -> None:
    """从人声中截取一段参考音频（用于声音克隆）"""
    # 跳过开头 2 秒（可能有噪音），截取 duration 秒
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-ss", "2",
        "-t", str(duration),
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
        str(ref_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await proc.communicate()

    if not ref_path.exists() or ref_path.stat().st_size == 0:
        # 如果截取失败（视频太短），直接用整段人声
        import shutil
        shutil.copy2(vocals_path, ref_path)

    logger.info(f"参考音频: {ref_path.stat().st_size / 1024:.0f} KB")


# ─── IndexTTS-2 配音生成 ──────────────────────────────────────

async def _generate_dubbed_segments(
    segments: list[SrtSegment],
    ref_audio: Path,
    work_dir: Path,
) -> list[tuple[SrtSegment, Path]]:
    """为每个字幕段生成配音，并用 atempo 匹配目标时长"""
    import sys

    # 添加 IndexTTS-2 到 Python 路径
    indextts_path = str(INDEXTTS_DIR)
    if indextts_path not in sys.path:
        sys.path.insert(0, indextts_path)

    loop = asyncio.get_running_loop()

    def _init_tts():
        from indextts.infer_v2 import IndexTTS2
        return IndexTTS2(
            cfg_path=str(INDEXTTS_CHECKPOINTS / "config.yaml"),
            model_dir=str(INDEXTTS_CHECKPOINTS),
            use_fp16=True,
            use_cuda_kernel=True,
        )

    logger.info("加载 IndexTTS-2 模型...")
    tts = await loop.run_in_executor(None, _init_tts)

    results = []
    for i, seg in enumerate(segments):
        raw_path = work_dir / f"seg_{i:04d}_raw.wav"
        final_path = work_dir / f"seg_{i:04d}.wav"

        # 生成配音
        def _infer(text=seg.text, out=str(raw_path)):
            tts.infer(
                spk_audio_prompt=str(ref_audio),
                text=text,
                output_path=out,
                verbose=False,
            )

        await loop.run_in_executor(None, _infer)

        if not raw_path.exists():
            logger.warning(f"段 {i} 配音生成失败，跳过")
            continue

        # 调整时长匹配字幕时间窗
        await _adjust_duration(raw_path, final_path, seg.duration)
        results.append((seg, final_path))

        if (i + 1) % 10 == 0 or i == len(segments) - 1:
            logger.info(f"配音进度: {i + 1}/{len(segments)}")

    return results


async def _adjust_duration(input_path: Path, output_path: Path, target_seconds: float) -> None:
    """用 ffmpeg atempo 调整音频时长"""
    current = await _get_duration(input_path)
    if current <= 0 or target_seconds <= 0:
        import shutil
        shutil.copy2(input_path, output_path)
        return

    tempo = current / target_seconds

    # atempo 范围 0.5-100.0，超出需要链式调用
    filters = []
    remaining = tempo
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter:a", ",".join(filters),
        "-acodec", "pcm_s16le",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await proc.communicate()

    if not output_path.exists():
        import shutil
        shutil.copy2(input_path, output_path)


async def _concat_segments_with_silence(
    segments: list[tuple[SrtSegment, Path]],
    output_path: Path,
    total_duration: float,
) -> None:
    """按字幕时间戳拼接配音段，段间填充静音"""
    if not segments:
        raise RuntimeError("没有可用的配音段")

    # 生成静音填充 + 配音段的 filter_complex
    inputs = []
    filter_parts = []

    for i, (seg, audio_path) in enumerate(segments):
        inputs.extend(["-i", str(audio_path)])

    # 构建 filter_complex：在每段前插入静音（对齐到字幕时间戳）
    concat_inputs = []
    for i, (seg, _) in enumerate(segments):
        # 当前段开始时间
        if i == 0 and seg.start > 0.01:
            # 第一段前的静音
            filter_parts.append(
                f"aevalsrc=0:d={seg.start:.3f}:s=44100:c=mono[sil{i}]"
            )
            concat_inputs.append(f"[sil{i}]")

        elif i > 0:
            prev_seg = segments[i - 1][0]
            gap = seg.start - prev_seg.end
            if gap > 0.01:
                filter_parts.append(
                    f"aevalsrc=0:d={gap:.3f}:s=44100:c=mono[sil{i}]"
                )
                concat_inputs.append(f"[sil{i}]")

        concat_inputs.append(f"[{i}:a]")

    # 尾部静音（如果配音比视频短）
    last_seg = segments[-1][0]
    tail_gap = total_duration - last_seg.end
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
