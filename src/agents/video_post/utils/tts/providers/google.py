from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import httpx

from ......utils.logger import get_logger
from ...tts_tags import prepare_provider_tts_text
from ..common import get_env_float, get_env_int
from ..schemas import TtsSynthesisBatchResult, TtsSynthesisContext, TtsSynthesisRequest, TtsSynthesisResult
from .base import TtsProvider

logger = get_logger(__name__)

GOOGLE_TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
VALID_GENDERS = {"SSML_VOICE_GENDER_UNSPECIFIED", "MALE", "FEMALE", "NEUTRAL"}


class GoogleTTSFatalError(RuntimeError):
    """Google TTS 不可重试错误。"""


def _get_google_tts_api_key() -> str:
    for candidate in (
        os.getenv("GOOGLE_TTS_API_KEY", "").strip(),
        os.getenv("GOOGLE_API_KEY", "").strip(),
    ):
        if candidate:
            return candidate
    raise RuntimeError(
        "未设置 Google TTS API Key。请设置以下任一环境变量：\n"
        "  GOOGLE_TTS_API_KEY（推荐）\n"
        "  GOOGLE_API_KEY"
    )


def _build_google_tts_voice_payload() -> dict[str, str]:
    language_code = os.getenv("GOOGLE_TTS_LANGUAGE_CODE", "zh-CN").strip() or "zh-CN"
    voice_name = os.getenv("GOOGLE_TTS_VOICE_NAME", "").strip()
    gender = os.getenv("GOOGLE_TTS_SSML_GENDER", "FEMALE").strip().upper()
    if gender not in VALID_GENDERS:
        logger.warning("GOOGLE_TTS_SSML_GENDER=%r 非法，回退 FEMALE", gender)
        gender = "FEMALE"

    payload = {
        "languageCode": language_code,
        "ssmlGender": gender,
    }
    if voice_name:
        payload["name"] = voice_name
    return payload


def _build_google_tts_audio_config_payload() -> dict[str, object]:
    speaking_rate = min(max(get_env_float("GOOGLE_TTS_SPEAKING_RATE", 1.0), 0.25), 4.0)
    pitch = min(max(get_env_float("GOOGLE_TTS_PITCH", 0.0), -20.0), 20.0)
    volume_gain_db = min(max(get_env_float("GOOGLE_TTS_VOLUME_GAIN_DB", 0.0), -96.0), 16.0)
    sample_rate_hz = get_env_int("GOOGLE_TTS_SAMPLE_RATE_HZ", 44100)
    return {
        "audioEncoding": "LINEAR16",
        "speakingRate": speaking_rate,
        "pitch": pitch,
        "volumeGainDb": volume_gain_db,
        "sampleRateHertz": sample_rate_hz,
    }


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


async def _synthesize_google_tts_segment_with_retry(
    client: httpx.AsyncClient,
    api_key: str,
    request: TtsSynthesisRequest,
    output_path: Path,
    voice_payload: dict[str, str],
    audio_payload: dict[str, object],
    timeout_seconds: float,
    retries: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Path | None]:
    text = prepare_provider_tts_text(
        text=request.text,
        provider="google",
        tone_tag=request.tone_tag,
    )
    if not text:
        return request.segment_index, None

    for attempt in range(1, retries + 1):
        try:
            async with semaphore:
                await _google_tts_synthesize(
                    client=client,
                    api_key=api_key,
                    text=text,
                    output_path=output_path,
                    voice_payload=voice_payload,
                    audio_payload=audio_payload,
                    timeout_seconds=timeout_seconds,
                )
            return request.segment_index, output_path
        except GoogleTTSFatalError as exc:
            logger.error("段 %s Google TTS 致命错误: %s", request.segment_index, exc)
            return request.segment_index, None
        except Exception as exc:
            if attempt >= retries:
                logger.error("段 %s Google TTS 失败（已重试 %s 次）: %s", request.segment_index, retries, exc)
                return request.segment_index, None
            wait_seconds = min(2 ** (attempt - 1), 8)
            logger.warning(
                "段 %s Google TTS 失败（%s/%s）: %s，%ss 后重试",
                request.segment_index,
                attempt,
                retries,
                exc,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    return request.segment_index, None


class GoogleTtsProvider(TtsProvider):
    provider_name = "google"

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

        api_key = _get_google_tts_api_key()
        voice_payload = _build_google_tts_voice_payload()
        audio_payload = _build_google_tts_audio_config_payload()
        retries = max(get_env_int("GOOGLE_TTS_RETRIES", 3), 1)
        timeout_seconds = max(get_env_float("GOOGLE_TTS_TIMEOUT_SECONDS", 45.0), 5.0)
        concurrency = max(get_env_int("GOOGLE_TTS_CONCURRENCY", 4), 1)
        semaphore = asyncio.Semaphore(concurrency)

        logger.info(
            "Google TTS 配置: language=%s, voice=%s, gender=%s, concurrency=%s",
            voice_payload.get("languageCode"),
            voice_payload.get("name", "<auto>"),
            voice_payload.get("ssmlGender"),
            concurrency,
        )

        async with httpx.AsyncClient() as client:
            tasks = [
                asyncio.create_task(
                    _synthesize_google_tts_segment_with_retry(
                        client=client,
                        api_key=api_key,
                        request=request,
                        output_path=context.work_dir / f"seg_{index:04d}_raw.wav",
                        voice_payload=voice_payload,
                        audio_payload=audio_payload,
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
                    logger.info("Google TTS 生成进度: %s/%s", completed, total)

        return TtsSynthesisBatchResult(
            requests=requests,
            success_map=success_map,
            provider_name=self.provider_name,
        )
