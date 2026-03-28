"""
视频配音工具 — 生成中文配音并替换视频音轨

流程：
1. 提取视频音频
2. 分离人声和背景音乐 (audio-separator / RoFormer)
3. 解析 SRT 字幕，按段调用 TTS（Fish Speech / Google TTS）
4. 用 ffmpeg atempo 调整每段配音时长匹配字幕时间窗
5. 拼接所有配音段 + 混合背景音乐
6. 替换视频音轨
"""

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .logger import get_logger

logger = get_logger(__name__)

# 项目路径与统一缓存路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
PROJECT_CACHE = PROJECT_ROOT / ".cache"
HF_HUB_CACHE_DIR = PROJECT_CACHE / "huggingface" / "hub"
MODELSCOPE_CACHE_DIR = PROJECT_CACHE / "modelscope"
TORCH_CACHE_DIR = PROJECT_CACHE / "torch"
AUDIO_SEPARATOR_MODEL_DIR = PROJECT_CACHE / "audio-separator" / "models"

# 人声分离模型（自动下载）
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
GOOGLE_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
VALID_GENDERS = {"SSML_VOICE_GENDER_UNSPECIFIED", "MALE", "FEMALE", "NEUTRAL"}
VALID_TTS_PROVIDERS = {"fish", "google", "s2cpp", "auto"}


class GoogleTTSFatalError(RuntimeError):
    """Google TTS 不可重试错误（鉴权、配置、请求参数问题）。"""


class FishTTSFatalError(RuntimeError):
    """Fish TTS 不可重试错误（配置、请求参数问题）。"""


class S2CppTTSFatalError(RuntimeError):
    """s2.cpp TTS 不可重试错误（配置、请求参数问题）。"""


def _get_tts_provider() -> str:
    raw = os.getenv("VIDEO_DUB_TTS_PROVIDER", "fish").strip().lower()
    if raw not in VALID_TTS_PROVIDERS:
        logger.warning(
            f"VIDEO_DUB_TTS_PROVIDER={raw!r} 非法，回退 fish "
            f"(可选: {', '.join(sorted(VALID_TTS_PROVIDERS))})"
        )
        return "fish"
    return raw


def _prepare_model_cache_env() -> None:
    """统一设置模型缓存目录到项目 .cache，避免落到仓库根 checkpoints。"""
    HF_HUB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MODELSCOPE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_SEPARATOR_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for key, value in _cache_env_vars().items():
        os.environ[key] = value

    # 如果 huggingface_hub 已经被导入，强制覆盖其运行时缓存常量。
    try:
        import huggingface_hub.constants as hf_constants
        if hasattr(hf_constants, "HF_HUB_CACHE"):
            hf_constants.HF_HUB_CACHE = str(HF_HUB_CACHE_DIR)
    except Exception:
        pass


def _cache_env_vars() -> dict[str, str]:
    return {
        "XDG_CACHE_HOME": str(PROJECT_CACHE),
        "HF_HOME": str(PROJECT_CACHE / "huggingface"),
        "HF_HUB_CACHE": str(HF_HUB_CACHE_DIR),
        "TRANSFORMERS_CACHE": str(HF_HUB_CACHE_DIR),
        "MODELSCOPE_CACHE": str(MODELSCOPE_CACHE_DIR),
        "TORCH_HOME": str(TORCH_CACHE_DIR),
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
    }


def _get_google_tts_api_key() -> str:
    def _find_key() -> str:
        keys = [
            os.getenv("GOOGLE_TTS_API_KEY", "").strip(),
            os.getenv("GOOGLE_API_KEY", "").strip(),
            os.getenv("GEMINI_API_KEY", "").strip(),
        ]
        for key in keys:
            if key:
                return key
        return ""

    key = _find_key()
    if key:
        return key

    # 兼容直接用脚本运行（未提前 export 环境变量）的场景。
    load_dotenv()
    key = _find_key()
    if key:
        return key

    raise RuntimeError(
        "未设置 Google TTS API Key。请设置以下任一环境变量：\n"
        "  GOOGLE_TTS_API_KEY（推荐）\n"
        "  GOOGLE_API_KEY\n"
        "  GEMINI_API_KEY"
    )


def _get_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} 不是有效浮点数，回退默认值 {default}")
        return default


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} 不是有效整数，回退默认值 {default}")
        return default


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


def _build_google_tts_voice_payload() -> dict[str, str]:
    language_code = os.getenv("GOOGLE_TTS_LANGUAGE_CODE", "zh-CN").strip() or "zh-CN"
    voice_name = os.getenv("GOOGLE_TTS_VOICE_NAME", "").strip()
    gender = os.getenv("GOOGLE_TTS_SSML_GENDER", "FEMALE").strip().upper()
    if gender not in VALID_GENDERS:
        logger.warning(f"GOOGLE_TTS_SSML_GENDER={gender!r} 非法，回退 FEMALE")
        gender = "FEMALE"

    voice: dict[str, str] = {
        "languageCode": language_code,
        "ssmlGender": gender,
    }
    if voice_name:
        voice["name"] = voice_name
    return voice


def _build_google_tts_audio_config_payload() -> dict[str, object]:
    speaking_rate = min(max(_get_env_float("GOOGLE_TTS_SPEAKING_RATE", 1.0), 0.25), 4.0)
    pitch = min(max(_get_env_float("GOOGLE_TTS_PITCH", 0.0), -20.0), 20.0)
    volume_gain_db = min(max(_get_env_float("GOOGLE_TTS_VOLUME_GAIN_DB", 0.0), -96.0), 16.0)
    sample_rate_hz = _get_env_int("GOOGLE_TTS_SAMPLE_RATE_HZ", 44100)

    return {
        "audioEncoding": "LINEAR16",
        "speakingRate": speaking_rate,
        "pitch": pitch,
        "volumeGainDb": volume_gain_db,
        "sampleRateHertz": sample_rate_hz,
    }


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
    def __init__(self, index: int, start: float, end: float, text: str, speaker_id: int = 0):
        self.index = index
        self.start = start
        self.end = end
        self.text = text
        self.speaker_id = speaker_id

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

        if text:
            segments.append(SrtSegment(index, start, end, text, speaker_id=speaker_id))

    return segments


def _srt_time_to_seconds(time_str: str) -> float:
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _merge_srt_segments(
    segments: list[SrtSegment],
    max_gap: float,
    max_duration: float,
    max_chars: int,
) -> list[SrtSegment]:
    """将相邻短字幕段合并，减少 TTS 请求次数。"""
    if not segments:
        return []
    merged: list[SrtSegment] = []
    cur = SrtSegment(
        index=segments[0].index,
        start=segments[0].start,
        end=segments[0].end,
        text=segments[0].text,
        speaker_id=segments[0].speaker_id,
    )
    for seg in segments[1:]:
        gap = seg.start - cur.end
        candidate_duration = seg.end - cur.start
        candidate_chars = len(cur.text) + 1 + len(seg.text)
        if (
            gap <= max_gap
            and candidate_duration <= max_duration
            and candidate_chars <= max_chars
            and seg.speaker_id == cur.speaker_id
        ):
            cur.end = seg.end
            cur.text = f"{cur.text} {seg.text}".strip()
        else:
            merged.append(cur)
            cur = SrtSegment(
                index=seg.index,
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker_id=seg.speaker_id,
            )
    merged.append(cur)
    return merged


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

async def _generate_dubbed_segments(
    segments: list[SrtSegment],
    work_dir: Path,
    reference_audio_path: Path,
    voice: str = "",
) -> list[tuple[SrtSegment, Path]]:
    """根据配置选择 TTS 后端，生成逐段配音并匹配字幕时长。"""
    if not segments:
        raise RuntimeError("字幕为空，无法生成配音")

    provider = _get_tts_provider()
    logger.info(f"TTS Provider: {provider}")

    if provider == "google":
        success_map = await _generate_dubbed_segments_google(segments, work_dir)
        return await _postprocess_dubbed_segments(
            success_map=success_map,
            segments=segments,
            work_dir=work_dir,
            empty_error="Google TTS 未生成任何可用配音段",
        )

    if provider == "fish":
        success_map = await _generate_dubbed_segments_fish(
            segments=segments,
            work_dir=work_dir,
            reference_audio_path=reference_audio_path,
        )
        return await _postprocess_dubbed_segments(
            success_map=success_map,
            segments=segments,
            work_dir=work_dir,
            empty_error="Fish TTS 未生成任何可用配音段",
        )

    if provider == "s2cpp":
        effective_segments, success_map = await _generate_dubbed_segments_s2cpp(
            segments=segments,
            work_dir=work_dir,
            reference_audio_path=reference_audio_path,
            voice=voice,
        )
        return await _postprocess_dubbed_segments(
            success_map=success_map,
            segments=effective_segments,
            work_dir=work_dir,
            empty_error="s2.cpp TTS 未生成任何可用配音段",
        )

    # auto: 优先 fish，失败后回退 s2.cpp，再回退 google
    try:
        success_map = await _generate_dubbed_segments_fish(
            segments=segments,
            work_dir=work_dir,
            reference_audio_path=reference_audio_path,
        )
        return await _postprocess_dubbed_segments(
            success_map=success_map,
            segments=segments,
            work_dir=work_dir,
            empty_error="Fish TTS 未生成任何可用配音段",
        )
    except Exception as exc:
        logger.warning(f"Fish TTS 失败，auto 模式回退 Google TTS: {exc}")
        try:
            effective_segments, success_map = await _generate_dubbed_segments_s2cpp(
                segments=segments,
                work_dir=work_dir,
                reference_audio_path=reference_audio_path,
                voice=voice,
            )
            return await _postprocess_dubbed_segments(
                success_map=success_map,
                segments=effective_segments,
                work_dir=work_dir,
                empty_error="s2.cpp TTS 未生成任何可用配音段",
            )
        except Exception as exc2:
            logger.warning(f"s2.cpp TTS 失败，auto 模式回退 Google TTS: {exc2}")
            success_map = await _generate_dubbed_segments_google(segments, work_dir)
            return await _postprocess_dubbed_segments(
                success_map=success_map,
                segments=segments,
                work_dir=work_dir,
                empty_error="Google TTS 未生成任何可用配音段",
            )


async def _postprocess_dubbed_segments(
    success_map: dict[int, Path],
    segments: list[SrtSegment],
    work_dir: Path,
    empty_error: str,
) -> list[tuple[SrtSegment, Path]]:
    results: list[tuple[SrtSegment, Path]] = []
    for i, seg in enumerate(segments):
        raw_path = success_map.get(i)
        if raw_path is None or not raw_path.exists():
            logger.warning(f"段 {i} 配音生成失败，跳过")
            continue

        final_path = work_dir / f"seg_{i:04d}.wav"
        await _adjust_duration(raw_path, final_path, seg.duration)
        results.append((seg, final_path))

    if not results:
        raise RuntimeError(empty_error)
    return results


async def _generate_dubbed_segments_google(
    segments: list[SrtSegment],
    work_dir: Path,
) -> dict[int, Path]:
    api_key = _get_google_tts_api_key()
    voice_payload = _build_google_tts_voice_payload()
    audio_payload = _build_google_tts_audio_config_payload()
    retries = max(_get_env_int("GOOGLE_TTS_RETRIES", 3), 1)
    timeout_seconds = max(_get_env_float("GOOGLE_TTS_TIMEOUT_SECONDS", 45.0), 5.0)
    concurrency = max(_get_env_int("GOOGLE_TTS_CONCURRENCY", 4), 1)
    semaphore = asyncio.Semaphore(concurrency)

    logger.info(
        "Google TTS 配置: "
        f"language={voice_payload.get('languageCode')}, "
        f"voice={voice_payload.get('name', '<auto>')}, "
        f"gender={voice_payload.get('ssmlGender')}, "
        f"concurrency={concurrency}"
    )

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(
                _synthesize_google_tts_segment_with_retry(
                    client=client,
                    api_key=api_key,
                    segment=seg,
                    index=i,
                    raw_output=work_dir / f"seg_{i:04d}_raw.wav",
                    voice_payload=voice_payload,
                    audio_payload=audio_payload,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    semaphore=semaphore,
                )
            )
            for i, seg in enumerate(segments)
        ]

        success_map: dict[int, Path] = {}
        completed = 0
        total = len(tasks)
        for done in asyncio.as_completed(tasks):
            idx, output_path = await done
            completed += 1
            if output_path is not None:
                success_map[idx] = output_path
            if completed % 10 == 0 or completed == total:
                logger.info(f"Google TTS 生成进度: {completed}/{total}")

    return success_map


async def _generate_dubbed_segments_fish(
    segments: list[SrtSegment],
    work_dir: Path,
    reference_audio_path: Path,
) -> dict[int, Path]:
    base_url = os.getenv("FISH_TTS_BASE_URL", "http://127.0.0.1:8080").strip().rstrip("/")
    retries = max(_get_env_int("FISH_TTS_RETRIES", 3), 1)
    timeout_seconds = max(_get_env_float("FISH_TTS_TIMEOUT_SECONDS", 180.0), 5.0)
    concurrency = max(_get_env_int("FISH_TTS_CONCURRENCY", 1), 1)
    semaphore = asyncio.Semaphore(concurrency)

    logger.info(
        "Fish TTS 配置: "
        f"base_url={base_url}, "
        f"concurrency={concurrency}, "
        f"timeout={timeout_seconds}s"
    )

    async with httpx.AsyncClient() as client:
        await _check_fish_tts_health(client, base_url, timeout_seconds)
        reference_id, delete_after = await _prepare_fish_reference(
            client=client,
            base_url=base_url,
            reference_audio_path=reference_audio_path,
            segments=segments,
            work_dir=work_dir,
            timeout_seconds=timeout_seconds,
        )

        try:
            tasks = [
                asyncio.create_task(
                    _synthesize_fish_tts_segment_with_retry(
                        client=client,
                        base_url=base_url,
                        segment=seg,
                        index=i,
                        raw_output=work_dir / f"seg_{i:04d}_raw.wav",
                        reference_id=reference_id,
                        timeout_seconds=timeout_seconds,
                        retries=retries,
                        semaphore=semaphore,
                    )
                )
                for i, seg in enumerate(segments)
            ]

            success_map: dict[int, Path] = {}
            completed = 0
            total = len(tasks)
            for done in asyncio.as_completed(tasks):
                idx, output_path = await done
                completed += 1
                if output_path is not None:
                    success_map[idx] = output_path
                if completed % 10 == 0 or completed == total:
                    logger.info(f"Fish TTS 生成进度: {completed}/{total}")
        finally:
            if delete_after:
                await _delete_fish_reference(
                    client=client,
                    base_url=base_url,
                    reference_id=reference_id,
                    timeout_seconds=timeout_seconds,
                )

    return success_map


def _resolve_env_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


_S2CPP_REFERENCES_DIR = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "references"

VOICE_REGISTRY: dict[str, dict] = {
    "liuyifei": {"desc": "温柔知性女声，适合旅行、生活方式、美妆、文艺类内容"},
    "dingzhen": {"desc": "纯朴自然男声，适合户外、旅行、自然风光、乡村生活类内容"},
    "zhoujielun": {"desc": "个性随性男声，适合音乐、潮流、运动、年轻人文化类内容"},
    "mabaoguo": {"desc": "中年幽默男声，适合搞笑、武术、健身、娱乐吐槽类内容"},
}
DEFAULT_VOICE = "liuyifei"


def _get_voice_ref_paths(voice: str) -> tuple[Path, Path]:
    voice_dir = _S2CPP_REFERENCES_DIR / voice
    wavs = sorted(voice_dir.glob("*_30s.wav"))
    txts = sorted(voice_dir.glob("*_30s.txt"))
    if not wavs or not txts:
        raise FileNotFoundError(f"音色 {voice} 缺少参考文件: {voice_dir}")
    return wavs[0], txts[0]


async def select_voice_async(topic: str, transcript: str = "") -> str:
    from pydantic_ai import Agent
    from .providers import get_text_model

    options = "\n".join(f"- {k}: {v['desc']}" for k, v in VOICE_REGISTRY.items())
    prompt = (
        f"根据以下视频内容，从可选音色中选择最合适的配音音色。\n\n"
        f"视频主题: {topic}\n"
        f"视频内容摘要: {transcript[:300]}\n\n"
        f"可选音色:\n{options}\n\n"
        f"只输出音色名称（如 liuyifei），不要任何解释。"
    )
    agent = Agent(model=get_text_model(), output_type=str)
    result = await agent.run(prompt)
    voice = result.output.strip().lower()
    if voice in VOICE_REGISTRY:
        logger.info(f"AI 选择配音音色: {voice} ({VOICE_REGISTRY[voice]['desc']})")
        return voice
    logger.warning(f"AI 返回未知音色 '{voice}'，使用默认: {DEFAULT_VOICE}")
    return DEFAULT_VOICE


async def assign_voices_to_speakers(
    topic: str, transcript: str, speaker_ids: list[int],
) -> dict[int, str]:
    if len(speaker_ids) <= 1:
        voice = await select_voice_async(topic, transcript)
        return {sid: voice for sid in speaker_ids}

    from pydantic_ai import Agent
    from .providers import get_text_model

    options = "\n".join(f"- {k}: {v['desc']}" for k, v in VOICE_REGISTRY.items())
    prompt = (
        f"一个视频中有 {len(speaker_ids)} 个说话人（编号: {speaker_ids}）。\n"
        f"视频主题: {topic}\n"
        f"内容摘要: {transcript[:300]}\n\n"
        f"请为每个说话人选择最合适的配音音色，不同说话人尽量用不同音色。\n\n"
        f"可选音色:\n{options}\n\n"
        f"每行输出格式: 说话人编号=音色名称\n"
        f"示例:\n0=liuyifei\n1=dingzhen\n"
    )
    agent = Agent(model=get_text_model(), output_type=str)
    result = await agent.run(prompt)

    mapping: dict[int, str] = {}
    for line in result.output.strip().split("\n"):
        if "=" in line:
            parts = line.split("=", 1)
            try:
                sid = int(parts[0].strip())
                voice = parts[1].strip().lower()
                if voice in VOICE_REGISTRY and sid in speaker_ids:
                    mapping[sid] = voice
            except ValueError:
                continue

    for sid in speaker_ids:
        if sid not in mapping:
            mapping[sid] = DEFAULT_VOICE

    logger.info(f"说话人音色分配: {mapping}")
    return mapping


def _build_s2cpp_reference_text(segments: list[SrtSegment], voice: str = "") -> str:
    configured = _normalize_tts_text(os.getenv("S2CPP_TTS_REFERENCE_TEXT", ""))
    if configured:
        return configured[:1200]

    voice = voice or DEFAULT_VOICE
    try:
        _, txt_path = _get_voice_ref_paths(voice)
        text = _normalize_tts_text(txt_path.read_text(encoding="utf-8", errors="ignore"))
        if text:
            return text[:1200]
    except FileNotFoundError:
        pass

    fallback = _build_fish_reference_text(segments)
    logger.warning("未找到音色参考文本，回退使用字幕内容片段作为 reference_text")
    return fallback


async def _prepare_s2cpp_reference_audio(
    reference_audio_path: Path,
    work_dir: Path,
    voice: str = "",
) -> Path | None:
    voice = voice or DEFAULT_VOICE
    try:
        wav_path, _ = _get_voice_ref_paths(voice)
        return wav_path
    except FileNotFoundError:
        pass

    configured = os.getenv("S2CPP_TTS_REFERENCE_AUDIO_PATH", "").strip()
    if configured:
        path = _resolve_env_path(configured)
        if not path.exists():
            raise RuntimeError(f"S2CPP_TTS_REFERENCE_AUDIO_PATH 不存在: {path}")
        return path

    auto_clip = _get_env_bool("S2CPP_TTS_AUTO_REFERENCE_CLIP", True)
    if not auto_clip:
        return None

    clip = work_dir / "s2cpp_reference.wav"
    start_seconds = max(_get_env_float("S2CPP_TTS_REFERENCE_START_SECONDS", 0.0), 0.0)
    duration_seconds = max(_get_env_float("S2CPP_TTS_REFERENCE_DURATION_SECONDS", 30.0), 1.0)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(reference_audio_path),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(clip),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not clip.exists() or clip.stat().st_size == 0:
        raise RuntimeError(f"s2.cpp 参考音频截取失败: {stderr.decode(errors='ignore')[-500:]}")
    return clip


_s2cpp_server_proc: subprocess.Popen | None = None

_S2CPP_EXE = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "build-cuda" / "Release" / "s2.exe"
_S2CPP_DLL_DIR = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "build-cuda" / "bin" / "Release"
_S2CPP_MODEL = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "models" / "s2-pro-q8_0.gguf"
_S2CPP_TOKENIZER = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "models" / "tokenizer.json"


async def _ensure_s2cpp_server(base_url: str, timeout_s: float = 180.0) -> None:
    global _s2cpp_server_proc

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(base_url, timeout=5.0)
            if r.status_code < 500:
                return
    except Exception:
        pass

    if not _S2CPP_EXE.exists():
        raise FileNotFoundError(f"s2.exe 不存在: {_S2CPP_EXE}")

    parsed = base_url.rstrip("/").rsplit(":", 1)
    port = int(parsed[-1]) if len(parsed) > 1 and parsed[-1].isdigit() else 3030
    host = "127.0.0.1"

    cuda_device = int(os.getenv("S2CPP_CUDA_DEVICE", "0"))
    env = os.environ.copy()
    env["PATH"] = f"{_S2CPP_DLL_DIR}{os.pathsep}{env.get('PATH', '')}"

    cmd = [
        str(_S2CPP_EXE), "-m", str(_S2CPP_MODEL), "-t", str(_S2CPP_TOKENIZER),
        "-c", str(cuda_device), "--server", "-H", host, "-P", str(port),
    ]
    logger.info(f"自动启动 s2.cpp server (port={port}, cuda={cuda_device})...")
    _s2cpp_server_proc = subprocess.Popen(
        cmd, cwd=str(PROJECT_ROOT / "submodules" / "s2.cpp_check"),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(base_url, timeout=3.0)
                if r.status_code < 500:
                    logger.info("s2.cpp server 已就绪")
                    return
        except Exception:
            pass
        if _s2cpp_server_proc.poll() is not None:
            raise RuntimeError(f"s2.cpp server 启动失败 (exit={_s2cpp_server_proc.returncode})")
        await asyncio.sleep(1.0)
    raise RuntimeError(f"s2.cpp server 启动超时 ({timeout_s}s)")


async def _check_s2cpp_tts_health(
    client: httpx.AsyncClient,
    base_url: str,
    timeout_seconds: float,
) -> None:
    await _ensure_s2cpp_server(base_url)
    response = await client.get(base_url, timeout=timeout_seconds)
    if response.status_code >= 500:
        detail = _extract_http_detail(response)
        raise RuntimeError(
            f"s2.cpp 服务不可用: HTTP {response.status_code}: {detail[:500]}"
        )


def _build_s2cpp_tts_params(target_duration_seconds: float) -> dict[str, object]:
    configured_max_new_tokens = _get_env_int("S2CPP_TTS_MAX_NEW_TOKENS", 0)
    if configured_max_new_tokens > 0:
        max_new_tokens = max(configured_max_new_tokens, 64)
    else:
        tokens_per_second = min(
            max(_get_env_float("S2CPP_TTS_TOKENS_PER_SECOND", 24.0), 8.0), 80.0
        )
        duration = max(target_duration_seconds, 1.0)
        estimated_tokens = int(duration * tokens_per_second)
        max_new_tokens = min(max(estimated_tokens, 80), 512)

    return {
        "max_new_tokens": max_new_tokens,
        "temperature": min(max(_get_env_float("S2CPP_TTS_TEMPERATURE", 0.72), 0.1), 1.5),
        "top_p": min(max(_get_env_float("S2CPP_TTS_TOP_P", 0.82), 0.1), 1.0),
        "top_k": max(_get_env_int("S2CPP_TTS_TOP_K", 30), 1),
        "min_tokens_before_end": max(_get_env_int("S2CPP_TTS_MIN_TOKENS_BEFORE_END", 0), 0),
        "n_threads": max(_get_env_int("S2CPP_TTS_THREADS", 4), 1),
        "verbose": _get_env_bool("S2CPP_TTS_VERBOSE", False),
    }


async def _s2cpp_tts_synthesize(
    client: httpx.AsyncClient,
    base_url: str,
    text: str,
    output_path: Path,
    reference_audio_path: Path | None,
    reference_text: str,
    target_duration_seconds: float,
    timeout_seconds: float,
) -> None:
    data: dict[str, str] = {
        "text": text,
        "params": json.dumps(
            _build_s2cpp_tts_params(target_duration_seconds), ensure_ascii=False
        ),
    }
    if reference_audio_path is not None:
        data["reference_text"] = reference_text
        with reference_audio_path.open("rb") as audio_file:
            response = await client.post(
                f"{base_url}/generate",
                data=data,
                files={"reference": ("reference.wav", audio_file, "audio/wav")},
                timeout=timeout_seconds,
            )
    else:
        response = await client.post(
            f"{base_url}/generate",
            data=data,
            timeout=timeout_seconds,
        )

    if response.status_code != 200:
        detail = _extract_http_detail(response)
        if response.status_code in {400, 401, 403, 404, 422}:
            raise S2CppTTSFatalError(f"HTTP {response.status_code}: {detail[:500]}")
        raise RuntimeError(f"HTTP {response.status_code}: {detail[:500]}")

    output_path.write_bytes(response.content)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("s2.cpp TTS 输出音频为空")


async def _synthesize_s2cpp_tts_segment_with_retry(
    client: httpx.AsyncClient,
    base_url: str,
    segment: SrtSegment,
    index: int,
    raw_output: Path,
    reference_audio_path: Path | None,
    reference_text: str,
    timeout_seconds: float,
    retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path | None]:
    text = _normalize_tts_text(segment.text)
    if not text:
        return index, None

    for attempt in range(1, retries + 1):
        try:
            async with semaphore:
                await _s2cpp_tts_synthesize(
                    client=client,
                    base_url=base_url,
                    text=text,
                    output_path=raw_output,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    target_duration_seconds=segment.duration,
                    timeout_seconds=timeout_seconds,
                )
            return index, raw_output
        except S2CppTTSFatalError as exc:
            logger.error(f"段 {index} s2.cpp TTS 致命错误: {exc}")
            return index, None
        except Exception as exc:
            if attempt >= retries:
                logger.error(f"段 {index} s2.cpp TTS 失败（已重试 {retries} 次）: {exc!r}")
                return index, None
            wait_seconds = min(2 ** (attempt - 1), 8)
            logger.warning(
                f"段 {index} s2.cpp TTS 失败（{attempt}/{retries}）: {exc!r}，"
                f"{wait_seconds}s 后重试"
            )
            await asyncio.sleep(wait_seconds)
    return index, None


async def _generate_dubbed_segments_s2cpp(
    segments: list[SrtSegment],
    work_dir: Path,
    reference_audio_path: Path,
    voice: str = "",
) -> tuple[list[SrtSegment], dict[int, Path]]:
    base_url = os.getenv("S2CPP_TTS_BASE_URL", "http://127.0.0.1:3030").strip().rstrip("/")
    retries = max(_get_env_int("S2CPP_TTS_RETRIES", 3), 1)
    timeout_seconds = max(_get_env_float("S2CPP_TTS_TIMEOUT_SECONDS", 240.0), 5.0)
    concurrency = max(_get_env_int("S2CPP_TTS_CONCURRENCY", 1), 1)
    semaphore = asyncio.Semaphore(concurrency)

    merge_segments = _get_env_bool("S2CPP_TTS_MERGE_SEGMENTS", True)
    max_gap = max(_get_env_float("S2CPP_TTS_MERGE_MAX_GAP", 1.2), 0.0)
    max_duration = max(_get_env_float("S2CPP_TTS_MERGE_MAX_DURATION", 12.0), 0.5)
    max_chars = max(_get_env_int("S2CPP_TTS_MERGE_MAX_CHARS", 120), 10)
    effective_segments = (
        _merge_srt_segments(segments, max_gap=max_gap, max_duration=max_duration, max_chars=max_chars)
        if merge_segments
        else segments
    )

    logger.info(
        "s2.cpp TTS 配置: "
        f"base_url={base_url}, "
        f"concurrency={concurrency}, "
        f"timeout={timeout_seconds}s, "
        f"segments={len(segments)}->{len(effective_segments)}"
    )

    speaker_ids = sorted(set(seg.speaker_id for seg in effective_segments))
    if len(speaker_ids) > 1:
        transcript = " ".join(seg.text[:30] for seg in effective_segments[:10])
        speaker_voice_map = await assign_voices_to_speakers(
            topic="", transcript=transcript, speaker_ids=speaker_ids,
        )
    else:
        v = voice or DEFAULT_VOICE
        speaker_voice_map = {sid: v for sid in speaker_ids}

    voice_refs: dict[str, tuple[Path | None, str]] = {}
    for v_name in set(speaker_voice_map.values()):
        ref_clip = await _prepare_s2cpp_reference_audio(reference_audio_path, work_dir, voice=v_name)
        ref_text = _build_s2cpp_reference_text(effective_segments, voice=v_name)
        voice_refs[v_name] = (ref_clip, ref_text)
        if ref_clip:
            logger.info(f"s2.cpp TTS 音色 {v_name} 参考音频: {ref_clip}")

    async with httpx.AsyncClient() as client:
        await _check_s2cpp_tts_health(client, base_url, timeout_seconds)

        tasks = []
        for i, seg in enumerate(effective_segments):
            seg_voice = speaker_voice_map.get(seg.speaker_id, DEFAULT_VOICE)
            ref_clip, ref_text = voice_refs.get(seg_voice, (None, ""))
            tasks.append(asyncio.create_task(
                _synthesize_s2cpp_tts_segment_with_retry(
                    client=client,
                    base_url=base_url,
                    segment=seg,
                    index=i,
                    raw_output=work_dir / f"seg_{i:04d}_raw.wav",
                    reference_audio_path=ref_clip,
                    reference_text=ref_text,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    semaphore=semaphore,
                )
            ))

        success_map: dict[int, Path] = {}
        completed = 0
        total = len(tasks)
        for done in asyncio.as_completed(tasks):
            idx, output_path = await done
            completed += 1
            if output_path is not None:
                success_map[idx] = output_path
            if completed % 10 == 0 or completed == total:
                logger.info(f"s2.cpp TTS 生成进度: {completed}/{total}")

    return effective_segments, success_map


def _normalize_tts_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"<[^>]+>", "", text)
    return text


def _extract_http_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body)
    except Exception:
        return response.text


def _build_fish_reference_text(segments: list[SrtSegment]) -> str:
    configured = _normalize_tts_text(os.getenv("FISH_TTS_REFERENCE_TEXT", ""))
    if configured:
        return configured[:240]

    collected: list[str] = []
    total_len = 0
    for seg in segments:
        text = _normalize_tts_text(seg.text)
        if not text:
            continue
        collected.append(text)
        total_len += len(text)
        if len(collected) >= 3 or total_len >= 180:
            break

    if collected:
        return " ".join(collected)
    return "这是一个中文声音克隆参考样本。"


def _build_fish_tts_payload(
    text: str,
    reference_id: str | None,
    target_duration_seconds: float | None = None,
) -> dict[str, object]:
    configured_max_new_tokens = _get_env_int("FISH_TTS_MAX_NEW_TOKENS", 0)
    if configured_max_new_tokens > 0:
        max_new_tokens = max(configured_max_new_tokens, 64)
    else:
        tokens_per_second = min(
            max(_get_env_float("FISH_TTS_TOKENS_PER_SECOND", 32.0), 10.0), 80.0
        )
        duration = max(target_duration_seconds or 0.0, 1.5)
        estimated_tokens = int(duration * tokens_per_second)
        max_new_tokens = min(max(estimated_tokens, 96), 512)

    payload: dict[str, object] = {
        "text": text,
        "format": "wav",
        "streaming": False,
        "chunk_length": max(_get_env_int("FISH_TTS_CHUNK_LENGTH", 200), 100),
        "max_new_tokens": max_new_tokens,
        "top_p": min(max(_get_env_float("FISH_TTS_TOP_P", 0.8), 0.1), 1.0),
        "temperature": min(max(_get_env_float("FISH_TTS_TEMPERATURE", 0.8), 0.1), 1.0),
        "repetition_penalty": min(
            max(_get_env_float("FISH_TTS_REPETITION_PENALTY", 1.1), 0.9), 2.0
        ),
        "normalize": _get_env_bool("FISH_TTS_NORMALIZE_TEXT", True),
        "use_memory_cache": "on" if _get_env_bool("FISH_TTS_USE_MEMORY_CACHE", True) else "off",
    }
    if reference_id:
        payload["reference_id"] = reference_id
    return payload


async def _check_fish_tts_health(
    client: httpx.AsyncClient,
    base_url: str,
    timeout_seconds: float,
) -> None:
    response = await client.get(f"{base_url}/v1/health", timeout=timeout_seconds)
    if response.status_code != 200:
        detail = _extract_http_detail(response)
        raise RuntimeError(
            f"Fish TTS 健康检查失败: HTTP {response.status_code}: {detail[:500]}"
        )


async def _extract_reference_clip(
    input_audio_path: Path,
    output_path: Path,
) -> None:
    start_seconds = max(_get_env_float("FISH_TTS_REFERENCE_START_SECONDS", 1.0), 0.0)
    duration_seconds = max(_get_env_float("FISH_TTS_REFERENCE_DURATION_SECONDS", 8.0), 1.0)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(input_audio_path),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"参考音频截取失败: {stderr.decode(errors='ignore')[-500:]}")


async def _prepare_fish_reference(
    client: httpx.AsyncClient,
    base_url: str,
    reference_audio_path: Path,
    segments: list[SrtSegment],
    work_dir: Path,
    timeout_seconds: float,
) -> tuple[str | None, bool]:
    provided_reference_id = os.getenv("FISH_TTS_REFERENCE_ID", "").strip()
    if provided_reference_id:
        logger.info(f"Fish TTS 使用已存在参考音色: {provided_reference_id}")
        return provided_reference_id, False

    auto_register = _get_env_bool("FISH_TTS_AUTO_REGISTER_REFERENCE", True)
    if not auto_register:
        logger.warning("未配置 Fish reference_id，且自动注册关闭，将使用无参考配音")
        return None, False

    reference_clip = work_dir / "fish_reference.wav"
    await _extract_reference_clip(reference_audio_path, reference_clip)

    generated_reference_id = f"dub_ref_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    reference_text = _build_fish_reference_text(segments)

    with reference_clip.open("rb") as audio_file:
        response = await client.post(
            f"{base_url}/v1/references/add?format=json",
            data={
                "id": generated_reference_id,
                "text": reference_text,
            },
            files={"audio": ("reference.wav", audio_file, "audio/wav")},
            timeout=timeout_seconds,
        )

    if response.status_code not in {200, 201}:
        detail = _extract_http_detail(response)
        raise RuntimeError(
            f"Fish 参考音色注册失败: HTTP {response.status_code}: {detail[:500]}"
        )

    delete_after = _get_env_bool("FISH_TTS_DELETE_REFERENCE_AFTER_RUN", True)
    logger.info(
        f"Fish reference 已注册: id={generated_reference_id}, "
        f"delete_after_run={delete_after}"
    )
    return generated_reference_id, delete_after


async def _delete_fish_reference(
    client: httpx.AsyncClient,
    base_url: str,
    reference_id: str | None,
    timeout_seconds: float,
) -> None:
    if not reference_id:
        return
    try:
        response = await client.request(
            "DELETE",
            f"{base_url}/v1/references/delete?format=json",
            json={"reference_id": reference_id},
            timeout=timeout_seconds,
        )
        if response.status_code >= 300:
            detail = _extract_http_detail(response)
            logger.warning(
                f"Fish reference 删除失败: id={reference_id}, "
                f"HTTP {response.status_code}: {detail[:300]}"
            )
        else:
            logger.info(f"Fish reference 已删除: {reference_id}")
    except Exception as exc:
        logger.warning(f"Fish reference 删除异常: id={reference_id}, error={exc}")


async def _synthesize_fish_tts_segment_with_retry(
    client: httpx.AsyncClient,
    base_url: str,
    segment: SrtSegment,
    index: int,
    raw_output: Path,
    reference_id: str | None,
    timeout_seconds: float,
    retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path | None]:
    text = _normalize_tts_text(segment.text)
    if not text:
        return index, None

    for attempt in range(1, retries + 1):
        try:
            async with semaphore:
                await _fish_tts_synthesize(
                    client=client,
                    base_url=base_url,
                    text=text,
                    output_path=raw_output,
                    reference_id=reference_id,
                    target_duration_seconds=segment.duration,
                    timeout_seconds=timeout_seconds,
                )
            return index, raw_output
        except FishTTSFatalError as exc:
            logger.error(f"段 {index} Fish TTS 致命错误: {exc}")
            return index, None
        except Exception as exc:
            if attempt >= retries:
                logger.error(f"段 {index} Fish TTS 失败（已重试 {retries} 次）: {exc!r}")
                return index, None
            wait_seconds = min(2 ** (attempt - 1), 8)
            logger.warning(
                f"段 {index} Fish TTS 失败（{attempt}/{retries}）: {exc!r}，"
                f"{wait_seconds}s 后重试"
            )
            await asyncio.sleep(wait_seconds)

    return index, None


async def _fish_tts_synthesize(
    client: httpx.AsyncClient,
    base_url: str,
    text: str,
    output_path: Path,
    reference_id: str | None,
    target_duration_seconds: float,
    timeout_seconds: float,
) -> None:
    response = await client.post(
        f"{base_url}/v1/tts",
        json=_build_fish_tts_payload(
            text=text,
            reference_id=reference_id,
            target_duration_seconds=target_duration_seconds,
        ),
        timeout=timeout_seconds,
    )
    if response.status_code != 200:
        detail = _extract_http_detail(response)
        if response.status_code in {400, 401, 403, 404, 422}:
            raise FishTTSFatalError(
                f"HTTP {response.status_code}: {detail[:500]}"
            )
        raise RuntimeError(f"HTTP {response.status_code}: {detail[:500]}")

    output_path.write_bytes(response.content)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Fish TTS 输出音频为空")


async def _synthesize_google_tts_segment_with_retry(
    client: httpx.AsyncClient,
    api_key: str,
    segment: SrtSegment,
    index: int,
    raw_output: Path,
    voice_payload: dict[str, str],
    audio_payload: dict[str, object],
    timeout_seconds: float,
    retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path | None]:
    text = _normalize_tts_text(segment.text)
    if not text:
        return index, None

    for attempt in range(1, retries + 1):
        try:
            async with semaphore:
                await _google_tts_synthesize(
                    client=client,
                    api_key=api_key,
                    text=text,
                    output_path=raw_output,
                    voice_payload=voice_payload,
                    audio_payload=audio_payload,
                    timeout_seconds=timeout_seconds,
                )
            return index, raw_output
        except GoogleTTSFatalError as exc:
            logger.error(f"段 {index} Google TTS 致命错误: {exc}")
            return index, None
        except Exception as exc:
            if attempt >= retries:
                logger.error(f"段 {index} Google TTS 失败（已重试 {retries} 次）: {exc}")
                return index, None
            wait_seconds = min(2 ** (attempt - 1), 8)
            logger.warning(
                f"段 {index} Google TTS 失败（{attempt}/{retries}）: {exc}，"
                f"{wait_seconds}s 后重试"
            )
            await asyncio.sleep(wait_seconds)

    return index, None


async def _google_tts_synthesize(
    client: httpx.AsyncClient,
    api_key: str,
    text: str,
    output_path: Path,
    voice_payload: dict[str, str],
    audio_payload: dict[str, object],
    timeout_seconds: float,
) -> None:
    response = await client.post(
        GOOGLE_TTS_ENDPOINT,
        params={"key": api_key},
        json={
            "input": {"text": text},
            "voice": voice_payload,
            "audioConfig": audio_payload,
        },
        timeout=timeout_seconds,
    )
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    error_obj = data.get("error") if isinstance(data, dict) else None
    error_status = ""
    error_message = ""
    if isinstance(error_obj, dict):
        error_status = str(error_obj.get("status", "")).strip()
        error_message = str(error_obj.get("message", "")).strip()

    if response.status_code != 200:
        if response.status_code in {400, 401, 403}:
            detail = error_message or str(data)
            raise GoogleTTSFatalError(
                f"HTTP {response.status_code} {error_status}: {detail[:500]}"
            )
        raise RuntimeError(
            f"HTTP {response.status_code} {error_status}: {(error_message or str(data))[:500]}"
        )

    audio_content = data.get("audioContent")
    if not audio_content:
        raise RuntimeError(f"Google TTS 响应缺少 audioContent: {str(data)[:500]}")

    output_path.write_bytes(base64.b64decode(audio_content))
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Google TTS 输出音频为空")


async def _adjust_duration(input_path: Path, output_path: Path, target_seconds: float) -> None:
    """用 ffmpeg atempo 调整音频时长"""
    current = await _get_duration(input_path)
    if current <= 0 or target_seconds <= 0:
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
