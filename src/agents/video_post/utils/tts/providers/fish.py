from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path

import httpx

from ......utils.logger import get_logger
from ...tts_tags import prepare_provider_tts_text, strip_tone_tag
from ..common import extract_http_detail, get_env_bool, get_env_float, get_env_int, normalize_tts_text
from ..schemas import TtsSynthesisBatchResult, TtsSynthesisContext, TtsSynthesisRequest, TtsSynthesisResult
from .base import TtsProvider

logger = get_logger(__name__)


class FishTTSFatalError(RuntimeError):
    """Fish TTS 不可重试错误。"""


def _build_fish_reference_text(requests: list[TtsSynthesisRequest]) -> str:
    configured = normalize_tts_text(strip_tone_tag(os.getenv("FISH_TTS_REFERENCE_TEXT", "")))
    if configured:
        return configured[:240]

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


def _build_fish_tts_payload(
    text: str,
    reference_id: str | None,
    target_duration_seconds: float | None = None,
) -> dict[str, object]:
    configured_max_new_tokens = get_env_int("FISH_TTS_MAX_NEW_TOKENS", 0)
    if configured_max_new_tokens > 0:
        max_new_tokens = max(configured_max_new_tokens, 64)
    else:
        tokens_per_second = min(
            max(get_env_float("FISH_TTS_TOKENS_PER_SECOND", 32.0), 10.0),
            80.0,
        )
        duration = max(target_duration_seconds or 0.0, 1.5)
        estimated_tokens = int(duration * tokens_per_second)
        max_new_tokens = min(max(estimated_tokens, 96), 512)

    payload: dict[str, object] = {
        "text": text,
        "format": "wav",
        "streaming": False,
        "chunk_length": max(get_env_int("FISH_TTS_CHUNK_LENGTH", 200), 100),
        "max_new_tokens": max_new_tokens,
        "top_p": min(max(get_env_float("FISH_TTS_TOP_P", 0.8), 0.1), 1.0),
        "temperature": min(max(get_env_float("FISH_TTS_TEMPERATURE", 0.8), 0.1), 1.0),
        "repetition_penalty": min(
            max(get_env_float("FISH_TTS_REPETITION_PENALTY", 1.1), 0.9),
            2.0,
        ),
        "normalize": get_env_bool("FISH_TTS_NORMALIZE_TEXT", True),
        "use_memory_cache": "on" if get_env_bool("FISH_TTS_USE_MEMORY_CACHE", True) else "off",
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
        detail = extract_http_detail(response)
        raise RuntimeError(
            f"Fish TTS 健康检查失败: HTTP {response.status_code}: {detail[:500]}"
        )


async def _extract_reference_clip(
    input_audio_path: Path,
    output_path: Path,
) -> None:
    start_seconds = max(get_env_float("FISH_TTS_REFERENCE_START_SECONDS", 1.0), 0.0)
    duration_seconds = max(get_env_float("FISH_TTS_REFERENCE_DURATION_SECONDS", 8.0), 1.0)
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
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"参考音频截取失败: {stderr.decode(errors='ignore')[-500:]}")


async def _prepare_fish_reference(
    client: httpx.AsyncClient,
    base_url: str,
    context: TtsSynthesisContext,
    requests: list[TtsSynthesisRequest],
    timeout_seconds: float,
) -> tuple[str | None, bool]:
    provided_reference_id = os.getenv("FISH_TTS_REFERENCE_ID", "").strip()
    if provided_reference_id:
        logger.info("Fish TTS 使用已存在参考音色: %s", provided_reference_id)
        return provided_reference_id, False

    auto_register = get_env_bool("FISH_TTS_AUTO_REGISTER_REFERENCE", True)
    if not auto_register:
        logger.warning("未配置 Fish reference_id，且自动注册关闭，将使用无参考配音")
        return None, False

    if context.reference_audio_path is None:
        raise RuntimeError("Fish TTS 自动注册参考音色需要 reference_audio_path")

    reference_clip = context.work_dir / "fish_reference.wav"
    await _extract_reference_clip(context.reference_audio_path, reference_clip)

    generated_reference_id = f"dub_ref_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    reference_text = _build_fish_reference_text(requests)
    with reference_clip.open("rb") as audio_file:
        response = await client.post(
            f"{base_url}/v1/references/add?format=json",
            data={"id": generated_reference_id, "text": reference_text},
            files={"audio": ("reference.wav", audio_file, "audio/wav")},
            timeout=timeout_seconds,
        )

    if response.status_code not in {200, 201}:
        detail = extract_http_detail(response)
        raise RuntimeError(
            f"Fish 参考音色注册失败: HTTP {response.status_code}: {detail[:500]}"
        )

    delete_after = get_env_bool("FISH_TTS_DELETE_REFERENCE_AFTER_RUN", True)
    logger.info(
        "Fish reference 已注册: id=%s, delete_after_run=%s",
        generated_reference_id,
        delete_after,
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
            detail = extract_http_detail(response)
            logger.warning(
                "Fish reference 删除失败: id=%s, HTTP %s: %s",
                reference_id,
                response.status_code,
                detail[:300],
            )
        else:
            logger.info("Fish reference 已删除: %s", reference_id)
    except Exception as exc:
        logger.warning("Fish reference 删除异常: id=%s, error=%s", reference_id, exc)


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
        detail = extract_http_detail(response)
        if response.status_code in {400, 401, 403, 404, 422}:
            raise FishTTSFatalError(f"HTTP {response.status_code}: {detail[:500]}")
        raise RuntimeError(f"HTTP {response.status_code}: {detail[:500]}")

    output_path.write_bytes(response.content)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Fish TTS 输出音频为空")


async def _synthesize_fish_tts_segment_with_retry(
    client: httpx.AsyncClient,
    base_url: str,
    request: TtsSynthesisRequest,
    output_path: Path,
    reference_id: str | None,
    timeout_seconds: float,
    retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path | None]:
    text = prepare_provider_tts_text(
        text=request.text,
        provider="fish",
        tone_tag=request.tone_tag,
    )
    if not text:
        return request.segment_index, None

    for attempt in range(1, retries + 1):
        try:
            async with semaphore:
                await _fish_tts_synthesize(
                    client=client,
                    base_url=base_url,
                    text=text,
                    output_path=output_path,
                    reference_id=reference_id,
                    target_duration_seconds=request.duration_seconds,
                    timeout_seconds=timeout_seconds,
                )
            return request.segment_index, output_path
        except FishTTSFatalError as exc:
            logger.error("段 %s Fish TTS 致命错误: %s", request.segment_index, exc)
            return request.segment_index, None
        except Exception as exc:
            if attempt >= retries:
                logger.error("段 %s Fish TTS 失败（已重试 %s 次）: %r", request.segment_index, retries, exc)
                return request.segment_index, None
            wait_seconds = min(2 ** (attempt - 1), 8)
            logger.warning(
                "段 %s Fish TTS 失败（%s/%s）: %r，%ss 后重试",
                request.segment_index,
                attempt,
                retries,
                exc,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    return request.segment_index, None


class FishTtsProvider(TtsProvider):
    provider_name = "fish"

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

        base_url = os.getenv("FISH_TTS_BASE_URL", "http://127.0.0.1:8080").strip().rstrip("/")
        retries = max(get_env_int("FISH_TTS_RETRIES", 3), 1)
        timeout_seconds = max(get_env_float("FISH_TTS_TIMEOUT_SECONDS", 180.0), 5.0)
        concurrency = max(get_env_int("FISH_TTS_CONCURRENCY", 1), 1)
        semaphore = asyncio.Semaphore(concurrency)

        logger.info(
            "Fish TTS 配置: base_url=%s, concurrency=%s, timeout=%ss",
            base_url,
            concurrency,
            timeout_seconds,
        )

        async with httpx.AsyncClient() as client:
            await _check_fish_tts_health(client, base_url, timeout_seconds)
            reference_id, delete_after = await _prepare_fish_reference(
                client=client,
                base_url=base_url,
                context=context,
                requests=requests,
                timeout_seconds=timeout_seconds,
            )

            try:
                tasks = [
                    asyncio.create_task(
                        _synthesize_fish_tts_segment_with_retry(
                            client=client,
                            base_url=base_url,
                            request=request,
                            output_path=context.work_dir / f"seg_{index:04d}_raw.wav",
                            reference_id=reference_id,
                            timeout_seconds=timeout_seconds,
                            retries=retries,
                            semaphore=semaphore,
                        )
                    )
                    for index, request in enumerate(requests)
                ]

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
                        logger.info("Fish TTS 生成进度: %s/%s", completed, total)
            finally:
                if delete_after:
                    await _delete_fish_reference(
                        client=client,
                        base_url=base_url,
                        reference_id=reference_id,
                        timeout_seconds=timeout_seconds,
                    )

        return TtsSynthesisBatchResult(
            requests=requests,
            success_map=success_map,
            provider_name=self.provider_name,
        )
