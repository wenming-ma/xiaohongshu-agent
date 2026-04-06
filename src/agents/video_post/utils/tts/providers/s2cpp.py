from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import httpx

from ......utils.logger import get_logger
from ...tts_tags import DEFAULT_TONE_TAG, prepare_provider_tts_text, strip_tone_tag
from ..common import (
    PROJECT_ROOT,
    extract_http_detail,
    get_env_bool,
    get_env_float,
    get_env_int,
    normalize_tts_text,
    resolve_env_path,
)
from ..schemas import TtsSynthesisBatchResult, TtsSynthesisContext, TtsSynthesisRequest, TtsSynthesisResult
from .base import TtsProvider

logger = get_logger(__name__)

_S2CPP_REFERENCES_DIR = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "references"
_S2CPP_EXE = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "build-cuda" / "Release" / "s2.exe"
_S2CPP_DLL_DIR = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "build-cuda" / "bin" / "Release"
_S2CPP_MODEL = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "models" / "s2-pro-q8_0.gguf"
_S2CPP_TOKENIZER = PROJECT_ROOT / "submodules" / "s2.cpp_check" / "models" / "tokenizer.json"
_S2CPP_CACHE_DIR = PROJECT_ROOT / ".cache" / "s2cpp"
_s2cpp_server_proc: subprocess.Popen | None = None

VOICE_REGISTRY: dict[str, dict[str, str]] = {
    "liuyifei": {"desc": "温柔知性女声，适合旅行、生活方式、美妆、文艺类内容"},
    "dingzhen": {"desc": "纯朴自然男声，适合户外、旅行、自然风光、乡村生活类内容"},
    "zhoujielun": {"desc": "个性随性男声，适合音乐、潮流、运动、年轻人文化类内容"},
    "mabaoguo": {"desc": "中年幽默男声，适合搞笑、武术、健身、娱乐吐槽类内容"},
}
DEFAULT_VOICE = "liuyifei"


class S2CppTTSFatalError(RuntimeError):
    """s2.cpp TTS 不可重试错误。"""


def _is_retryable_s2cpp_http_error(status_code: int, detail: str) -> bool:
    normalized = (detail or "").lower()
    if status_code == 400:
        return any(
            marker in normalized
            for marker in ("synthesis failed", "internal error", "engine busy")
        )
    return status_code >= 500


def _get_voice_ref_paths(voice: str) -> tuple[Path, Path]:
    voice_dir = _S2CPP_REFERENCES_DIR / voice
    wavs = sorted(voice_dir.glob("*_30s.wav"))
    txts = sorted(voice_dir.glob("*_30s.txt"))
    if not wavs or not txts:
        raise FileNotFoundError(f"音色 {voice} 缺少参考文件: {voice_dir}")
    return wavs[0], txts[0]


async def select_voice_async(topic: str, transcript: str = "") -> str:
    options = "\n".join(f"- {key}: {value['desc']}" for key, value in VOICE_REGISTRY.items())
    prompt = (
        "根据以下视频内容，从可选音色中选择最合适的配音音色。\n\n"
        f"视频主题: {topic}\n"
        f"视频内容摘要: {transcript[:300]}\n\n"
        f"可选音色:\n{options}\n\n"
        "只输出音色名称（如 liuyifei），不要任何解释。"
    )
    try:
        from pydantic_ai import Agent
        from ......utils.providers.selector import get_text_model

        agent = Agent(model=get_text_model(), output_type=str)
        result = await agent.run(prompt)
        voice = result.output.strip().lower()
    except Exception as exc:
        logger.warning("AI 选音不可用，回退默认音色 %s: %s", DEFAULT_VOICE, exc)
        return DEFAULT_VOICE

    if voice in VOICE_REGISTRY:
        logger.info("AI 选择配音音色: %s (%s)", voice, VOICE_REGISTRY[voice]["desc"])
        return voice
    logger.warning("AI 返回未知音色 %r，使用默认: %s", voice, DEFAULT_VOICE)
    return DEFAULT_VOICE


async def assign_voices_to_speakers(
    transcript: str,
    speaker_ids: list[int],
) -> dict[int, str]:
    if len(speaker_ids) <= 1:
        voice = await select_voice_async("", transcript)
        return {speaker_id: voice for speaker_id in speaker_ids}

    options = "\n".join(f"- {key}: {value['desc']}" for key, value in VOICE_REGISTRY.items())
    prompt = (
        f"一个视频中有 {len(speaker_ids)} 个说话人（编号: {speaker_ids}）。\n"
        f"内容摘要: {transcript[:300]}\n\n"
        "请为每个说话人选择最合适的配音音色，不同说话人尽量用不同音色。\n\n"
        f"可选音色:\n{options}\n\n"
        "每行输出格式: 说话人编号=音色名称\n"
        "示例:\n0=liuyifei\n1=dingzhen\n"
    )
    try:
        from pydantic_ai import Agent
        from ......utils.providers.selector import get_text_model

        agent = Agent(model=get_text_model(), output_type=str)
        result = await agent.run(prompt)
    except Exception as exc:
        logger.warning("多说话人 AI 选音不可用，统一回退默认音色 %s: %s", DEFAULT_VOICE, exc)
        return {speaker_id: DEFAULT_VOICE for speaker_id in speaker_ids}

    mapping: dict[int, str] = {}
    for line in result.output.strip().splitlines():
        if "=" not in line:
            continue
        speaker_raw, voice_raw = line.split("=", 1)
        try:
            speaker_id = int(speaker_raw.strip())
        except ValueError:
            continue
        voice = voice_raw.strip().lower()
        if voice in VOICE_REGISTRY and speaker_id in speaker_ids:
            mapping[speaker_id] = voice

    for speaker_id in speaker_ids:
        mapping.setdefault(speaker_id, DEFAULT_VOICE)

    logger.info("说话人音色分配: %s", mapping)
    return mapping


def _merge_requests(
    requests: list[TtsSynthesisRequest],
    max_gap: float,
    max_duration: float,
    max_chars: int,
) -> list[TtsSynthesisRequest]:
    if not requests:
        return []

    merged: list[TtsSynthesisRequest] = []
    current = TtsSynthesisRequest(
        segment_index=requests[0].segment_index,
        text=requests[0].text,
        language=requests[0].language,
        voice=requests[0].voice,
        tone_tag=requests[0].tone_tag,
        speaker_id=requests[0].speaker_id,
        target_start=requests[0].target_start,
        target_end=requests[0].target_end,
        target_duration_seconds=requests[0].duration_seconds,
    )
    for request in requests[1:]:
        gap = request.target_start - current.target_end
        candidate_duration = request.target_end - current.target_start
        candidate_chars = len(current.text) + 1 + len(request.text)
        if (
            gap <= max_gap
            and candidate_duration <= max_duration
            and candidate_chars <= max_chars
            and request.speaker_id == current.speaker_id
        ):
            current.target_end = request.target_end
            current.target_duration_seconds = max(current.target_end - current.target_start, 0.0)
            current.text = f"{current.text} {request.text}".strip()
            if request.tone_tag and request.tone_tag != current.tone_tag:
                current.tone_tag = DEFAULT_TONE_TAG
        else:
            merged.append(current)
            current = TtsSynthesisRequest(
                segment_index=request.segment_index,
                text=request.text,
                language=request.language,
                voice=request.voice,
                tone_tag=request.tone_tag,
                speaker_id=request.speaker_id,
                target_start=request.target_start,
                target_end=request.target_end,
                target_duration_seconds=request.duration_seconds,
            )
    merged.append(current)
    return merged


def _build_fish_reference_text(requests: list[TtsSynthesisRequest]) -> str:
    collected: list[str] = []
    total_len = 0
    for request in requests:
        text = normalize_tts_text(strip_tone_tag(request.text))
        if not text:
            continue
        collected.append(text)
        total_len += len(text)
        if len(collected) >= 3 or total_len >= 180:
            break
    if collected:
        return " ".join(collected)
    return "这是一个中文声音克隆参考样本。"


def _build_s2cpp_reference_text(requests: list[TtsSynthesisRequest], voice: str = "") -> str:
    configured = normalize_tts_text(strip_tone_tag(os.getenv("S2CPP_TTS_REFERENCE_TEXT", "")))
    if configured:
        return configured[:1200]

    voice = voice or DEFAULT_VOICE
    try:
        _, txt_path = _get_voice_ref_paths(voice)
        text = normalize_tts_text(strip_tone_tag(txt_path.read_text(encoding="utf-8", errors="ignore")))
        if text:
            return text[:1200]
    except FileNotFoundError:
        pass

    fallback = _build_fish_reference_text(requests)
    logger.warning("未找到音色参考文本，回退使用字幕内容片段作为 reference_text")
    return fallback


async def _prepare_s2cpp_reference_audio(
    reference_audio_path: Path | None,
    context: TtsSynthesisContext,
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
        path = resolve_env_path(configured)
        if not path.exists():
            raise RuntimeError(f"S2CPP_TTS_REFERENCE_AUDIO_PATH 不存在: {path}")
        return path

    auto_clip = get_env_bool("S2CPP_TTS_AUTO_REFERENCE_CLIP", True)
    if not auto_clip:
        return None
    if reference_audio_path is None:
        raise RuntimeError("s2.cpp 自动截取参考音频需要 reference_audio_path")

    clip = context.work_dir / "s2cpp_reference.wav"
    start_seconds = max(get_env_float("S2CPP_TTS_REFERENCE_START_SECONDS", 0.0), 0.0)
    duration_seconds = max(get_env_float("S2CPP_TTS_REFERENCE_DURATION_SECONDS", 30.0), 1.0)
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
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not clip.exists() or clip.stat().st_size == 0:
        raise RuntimeError(f"s2.cpp 参考音频截取失败: {stderr.decode(errors='ignore')[-500:]}")
    return clip


async def _ensure_s2cpp_server(base_url: str, timeout_s: float = 180.0) -> None:
    global _s2cpp_server_proc

    if await _probe_s2cpp_server(base_url, timeout_seconds=5.0):
        return

    if not _S2CPP_EXE.exists():
        raise FileNotFoundError(f"s2.exe 不存在: {_S2CPP_EXE}")

    parsed = base_url.rstrip("/").rsplit(":", 1)
    port = int(parsed[-1]) if len(parsed) > 1 and parsed[-1].isdigit() else 3030
    host = "127.0.0.1"
    cuda_device = int(os.getenv("S2CPP_CUDA_DEVICE", "0"))
    start_retries = max(get_env_int("S2CPP_SERVER_START_RETRIES", 2), 1)

    for attempt in range(1, start_retries + 1):
        log_path = _build_s2cpp_server_log_path(port, attempt)
        logger.info(
            "自动启动 s2.cpp server (port=%s, cuda=%s, attempt=%s/%s)...",
            port,
            cuda_device,
            attempt,
            start_retries,
        )
        _s2cpp_server_proc = _spawn_s2cpp_server(
            host=host,
            port=port,
            cuda_device=cuda_device,
            log_path=log_path,
        )

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if await _probe_s2cpp_server(base_url, timeout_seconds=3.0):
                logger.info("s2.cpp server 已就绪")
                return

            code = _s2cpp_server_proc.poll()
            if code is not None:
                snippet = _read_s2cpp_server_log(log_path)
                if attempt >= start_retries:
                    raise RuntimeError(
                        f"s2.cpp server 启动失败 (attempt={attempt}/{start_retries}, exit={code})"
                        + (f": {snippet}" if snippet else "")
                    )
                logger.warning(
                    "s2.cpp server 启动失败 (attempt=%s/%s, exit=%s)，重试。%s",
                    attempt,
                    start_retries,
                    code,
                    snippet or "无可用启动日志",
                )
                await asyncio.sleep(min(float(attempt * 2), 5.0))
                break

            await asyncio.sleep(1.0)
        else:
            _terminate_s2cpp_server_proc(_s2cpp_server_proc)
            snippet = _read_s2cpp_server_log(log_path)
            raise RuntimeError(
                f"s2.cpp server 启动超时 ({timeout_s}s)"
                + (f": {snippet}" if snippet else "")
            )

    raise RuntimeError("s2.cpp server 启动失败：已超过最大重试次数")


def _build_s2cpp_server_log_path(port: int, attempt: int) -> Path:
    _S2CPP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _S2CPP_CACHE_DIR / f"server-{port}-attempt{attempt}.log"


def _spawn_s2cpp_server(
    *,
    host: str,
    port: int,
    cuda_device: int,
    log_path: Path,
) -> subprocess.Popen:
    env = os.environ.copy()
    env["PATH"] = f"{_S2CPP_DLL_DIR}{os.pathsep}{env.get('PATH', '')}"
    cmd = [
        str(_S2CPP_EXE),
        "-m",
        str(_S2CPP_MODEL),
        "-t",
        str(_S2CPP_TOKENIZER),
        "-c",
        str(cuda_device),
        "--server",
        "-H",
        host,
        "-P",
        str(port),
    ]
    with log_path.open("w", encoding="utf-8", errors="ignore") as log_file:
        return subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT / "submodules" / "s2.cpp_check"),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )


def _read_s2cpp_server_log(log_path: Path, max_chars: int = 1200) -> str:
    if not log_path.exists():
        return ""
    content = log_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not content:
        return ""
    normalized = " ".join(content.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[-max_chars:]


def _terminate_s2cpp_server_proc(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.kill()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


async def _probe_s2cpp_server(base_url: str, timeout_seconds: float) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, timeout=timeout_seconds)
            return response.status_code < 500
    except Exception:
        return False


async def _check_s2cpp_tts_health(
    client: httpx.AsyncClient,
    base_url: str,
    timeout_seconds: float,
) -> None:
    await _ensure_s2cpp_server(base_url)
    response = await client.get(base_url, timeout=timeout_seconds)
    if response.status_code >= 500:
        detail = extract_http_detail(response)
        raise RuntimeError(
            f"s2.cpp 服务不可用: HTTP {response.status_code}: {detail[:500]}"
        )


def _build_s2cpp_tts_params(target_duration_seconds: float) -> dict[str, object]:
    configured_max_new_tokens = get_env_int("S2CPP_TTS_MAX_NEW_TOKENS", 0)
    if configured_max_new_tokens > 0:
        max_new_tokens = max(configured_max_new_tokens, 64)
    else:
        tokens_per_second = min(
            max(get_env_float("S2CPP_TTS_TOKENS_PER_SECOND", 24.0), 8.0),
            80.0,
        )
        duration = max(target_duration_seconds, 1.0)
        estimated_tokens = int(duration * tokens_per_second)
        max_new_tokens = min(max(estimated_tokens, 80), 512)

    return {
        "max_new_tokens": max_new_tokens,
        "temperature": min(max(get_env_float("S2CPP_TTS_TEMPERATURE", 0.72), 0.1), 1.5),
        "top_p": min(max(get_env_float("S2CPP_TTS_TOP_P", 0.82), 0.1), 1.0),
        "top_k": max(get_env_int("S2CPP_TTS_TOP_K", 30), 1),
        "min_tokens_before_end": max(get_env_int("S2CPP_TTS_MIN_TOKENS_BEFORE_END", 0), 0),
        "n_threads": max(get_env_int("S2CPP_TTS_THREADS", 4), 1),
        "verbose": get_env_bool("S2CPP_TTS_VERBOSE", False),
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
            _build_s2cpp_tts_params(target_duration_seconds),
            ensure_ascii=False,
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
        detail = extract_http_detail(response)
        if _is_retryable_s2cpp_http_error(response.status_code, detail):
            raise RuntimeError(f"HTTP {response.status_code}: {detail[:500]}")
        if response.status_code in {400, 401, 403, 404, 422}:
            raise S2CppTTSFatalError(f"HTTP {response.status_code}: {detail[:500]}")
        raise RuntimeError(f"HTTP {response.status_code}: {detail[:500]}")

    output_path.write_bytes(response.content)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("s2.cpp TTS 输出音频为空")


async def _synthesize_s2cpp_tts_segment_with_retry(
    client: httpx.AsyncClient,
    base_url: str,
    request: TtsSynthesisRequest,
    output_path: Path,
    reference_audio_path: Path | None,
    reference_text: str,
    timeout_seconds: float,
    retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path | None]:
    text = prepare_provider_tts_text(
        text=request.text,
        provider="s2cpp",
        tone_tag=request.tone_tag,
    )
    if not text:
        return request.segment_index, None

    for attempt in range(1, retries + 1):
        try:
            async with semaphore:
                await _s2cpp_tts_synthesize(
                    client=client,
                    base_url=base_url,
                    text=text,
                    output_path=output_path,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    target_duration_seconds=request.duration_seconds,
                    timeout_seconds=timeout_seconds,
                )
            return request.segment_index, output_path
        except S2CppTTSFatalError as exc:
            logger.error("段 %s s2.cpp TTS 致命错误: %s", request.segment_index, exc)
            return request.segment_index, None
        except Exception as exc:
            if attempt >= retries:
                logger.error("段 %s s2.cpp TTS 失败（已重试 %s 次）: %r", request.segment_index, retries, exc)
                return request.segment_index, None
            wait_seconds = min(2 ** (attempt - 1), 8)
            logger.warning(
                "段 %s s2.cpp TTS 失败（%s/%s）: %r，%ss 后重试",
                request.segment_index,
                attempt,
                retries,
                exc,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
    return request.segment_index, None


class S2CppTtsProvider(TtsProvider):
    provider_name = "s2cpp"

    async def synthesize_many(
        self,
        requests: list[TtsSynthesisRequest],
        context: TtsSynthesisContext,
    ) -> TtsSynthesisBatchResult:
        if not requests:
            return TtsSynthesisBatchResult(
                requests=[],
                success_map={},
                provider_name=self.provider_name,
            )

        base_url = os.getenv("S2CPP_TTS_BASE_URL", "http://127.0.0.1:3030").strip().rstrip("/")
        retries = max(get_env_int("S2CPP_TTS_RETRIES", 5), 1)
        timeout_seconds = max(get_env_float("S2CPP_TTS_TIMEOUT_SECONDS", 240.0), 5.0)
        concurrency = max(get_env_int("S2CPP_TTS_CONCURRENCY", 1), 1)
        semaphore = asyncio.Semaphore(concurrency)

        merge_segments = get_env_bool("S2CPP_TTS_MERGE_SEGMENTS", False)
        max_gap = max(get_env_float("S2CPP_TTS_MERGE_MAX_GAP", 1.2), 0.0)
        max_duration = max(get_env_float("S2CPP_TTS_MERGE_MAX_DURATION", 12.0), 0.5)
        max_chars = max(get_env_int("S2CPP_TTS_MERGE_MAX_CHARS", 120), 10)
        effective_requests = (
            _merge_requests(requests, max_gap=max_gap, max_duration=max_duration, max_chars=max_chars)
            if merge_segments
            else requests
        )

        logger.info(
            "s2.cpp TTS 配置: base_url=%s, concurrency=%s, timeout=%ss, segments=%s->%s",
            base_url,
            concurrency,
            timeout_seconds,
            len(requests),
            len(effective_requests),
        )

        speaker_ids = sorted({request.speaker_id for request in effective_requests})
        if len(speaker_ids) > 1:
            transcript = " ".join(strip_tone_tag(request.text)[:30] for request in effective_requests[:10])
            speaker_voice_map = await assign_voices_to_speakers(transcript=transcript, speaker_ids=speaker_ids)
        else:
            selected_voice = context.voice or DEFAULT_VOICE
            speaker_voice_map = {speaker_id: selected_voice for speaker_id in speaker_ids}

        voice_refs: dict[str, tuple[Path | None, str]] = {}
        for voice_name in set(speaker_voice_map.values()):
            ref_clip = await _prepare_s2cpp_reference_audio(
                context.reference_audio_path,
                context=context,
                voice=voice_name,
            )
            ref_text = _build_s2cpp_reference_text(effective_requests, voice=voice_name)
            voice_refs[voice_name] = (ref_clip, ref_text)
            if ref_clip is not None:
                logger.info("s2.cpp TTS 音色 %s 参考音频: %s", voice_name, ref_clip)

        async with httpx.AsyncClient() as client:
            await _check_s2cpp_tts_health(client, base_url, timeout_seconds)
            tasks = []
            for index, request in enumerate(effective_requests):
                segment_voice = speaker_voice_map.get(request.speaker_id, DEFAULT_VOICE)
                ref_clip, ref_text = voice_refs.get(segment_voice, (None, ""))
                tasks.append(
                    asyncio.create_task(
                        _synthesize_s2cpp_tts_segment_with_retry(
                            client=client,
                            base_url=base_url,
                            request=request,
                            output_path=context.work_dir / f"seg_{index:04d}_raw.wav",
                            reference_audio_path=ref_clip,
                            reference_text=ref_text,
                            timeout_seconds=timeout_seconds,
                            retries=retries,
                            semaphore=semaphore,
                        )
                    )
                )

            success_map: dict[int, TtsSynthesisResult] = {}
            completed = 0
            total = len(tasks)
            for done in asyncio.as_completed(tasks):
                index, output_path = await done
                completed += 1
                if output_path is not None:
                    success_map[index] = TtsSynthesisResult(
                        audio_path=output_path,
                        provider_name=self.provider_name,
                        timing_source="none",
                    )
                if completed % 10 == 0 or completed == total:
                    logger.info("s2.cpp TTS 生成进度: %s/%s", completed, total)

        return TtsSynthesisBatchResult(
            requests=effective_requests,
            success_map=success_map,
            provider_name=self.provider_name,
        )
