from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ......utils.logger import get_logger
from ...tts_tags import normalize_tone_tag, split_tone_tag
from ..common import PROJECT_ROOT, get_env_float, get_env_int, normalize_tts_text, resolve_env_path
from ..schemas import TtsSynthesisBatchResult, TtsSynthesisContext, TtsSynthesisRequest, TtsSynthesisResult
from .base import TtsProvider

logger = get_logger(__name__)

DEFAULT_QWEN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_QWEN_SPEAKER = "Vivian"

_QWEN_TTS_PYTHON = PROJECT_ROOT / "submodules" / "qwen3-tts" / ".venv" / "Scripts" / "python.exe"
_QWEN_TTS_RUNNER = PROJECT_ROOT / "scripts" / "qwen_tts_batch.py"

_QWEN_TONE_TAG_TO_INSTRUCT = {
    "neutral": "",
    "friendly": "用亲切友好的语气说",
    "playful": "用俏皮活泼的语气说",
    "casual": "用轻松随意的语气说",
    "confident": "用自信的语气说",
    "questioning": "用疑惑好奇的语气说",
    "matter of fact": "用平淡陈述的语气说",
    "excited": "用兴奋激动的语气说",
    "calm": "用平静自然的语气说",
    "serious": "用认真克制的语气说",
    "gentle": "用温柔放松的语气说",
}

_QWEN_LANGUAGE_ALIASES = {
    "": "Auto",
    "auto": "Auto",
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh_cn": "Chinese",
    "cn": "Chinese",
    "chinese": "Chinese",
    "en": "English",
    "en-us": "English",
    "en_us": "English",
    "english": "English",
    "ja": "Japanese",
    "jp": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "kr": "Korean",
    "korean": "Korean",
    "de": "German",
    "german": "German",
    "fr": "French",
    "french": "French",
    "ru": "Russian",
    "russian": "Russian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "es": "Spanish",
    "spanish": "Spanish",
    "it": "Italian",
    "italian": "Italian",
}


def _resolve_qwen_python_path() -> Path:
    configured = os.getenv("QWEN_TTS_PYTHON", "").strip()
    path = resolve_env_path(configured) if configured else _QWEN_TTS_PYTHON
    if not path.exists():
        raise FileNotFoundError(f"Qwen TTS Python 不存在: {path}")
    return path


def _resolve_qwen_runner_path() -> Path:
    configured = os.getenv("QWEN_TTS_RUNNER", "").strip()
    path = resolve_env_path(configured) if configured else _QWEN_TTS_RUNNER
    if not path.exists():
        raise FileNotFoundError(f"Qwen TTS runner 不存在: {path}")
    return path


def _resolve_qwen_model_id() -> str:
    return os.getenv("QWEN_TTS_MODEL_ID", "").strip() or DEFAULT_QWEN_MODEL_ID


def _resolve_qwen_speaker(request: TtsSynthesisRequest, context: TtsSynthesisContext) -> str:
    for candidate in (
        request.voice.strip(),
        context.voice.strip(),
        os.getenv("QWEN_TTS_SPEAKER", "").strip(),
        DEFAULT_QWEN_SPEAKER,
    ):
        if candidate:
            return candidate
    return DEFAULT_QWEN_SPEAKER


def _normalize_qwen_language(language: str) -> str:
    normalized = (language or "").strip().lower()
    return _QWEN_LANGUAGE_ALIASES.get(normalized, language.strip() or "Auto")


def _resolve_qwen_text_and_instruct(request: TtsSynthesisRequest) -> tuple[str, str]:
    extracted_tag, stripped_text = split_tone_tag(request.text)
    normalized_text = normalize_tts_text(stripped_text or request.text)
    if not normalized_text:
        return "", ""

    tone_tag = normalize_tone_tag(request.tone_tag or extracted_tag)
    instruct = _QWEN_TONE_TAG_TO_INSTRUCT.get(tone_tag, "")
    return normalized_text, instruct


def _build_qwen_batch_request(
    requests: list[TtsSynthesisRequest],
    context: TtsSynthesisContext,
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for index, request in enumerate(requests):
        text, instruct = _resolve_qwen_text_and_instruct(request)
        if not text:
            continue

        items.append(
            {
                "segment_index": index,
                "text": text,
                "language": _normalize_qwen_language(request.language),
                "speaker": _resolve_qwen_speaker(request, context),
                "instruct": instruct,
                "output_path": str(context.work_dir / f"seg_{index:04d}_raw.wav"),
            }
        )

    payload: dict[str, object] = {
        "model_id": _resolve_qwen_model_id(),
        "device": os.getenv("QWEN_TTS_DEVICE", "").strip() or "cuda:0",
        "dtype": os.getenv("QWEN_TTS_DTYPE", "").strip() or "float16",
        "batch_size": max(get_env_int("QWEN_TTS_BATCH_SIZE", 1), 1),
        "items": items,
    }
    attn_implementation = os.getenv("QWEN_TTS_ATTN_IMPLEMENTATION", "").strip()
    if attn_implementation:
        payload["attn_implementation"] = attn_implementation
    return payload


async def _terminate_qwen_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.kill()
    try:
        await proc.wait()
    except Exception:
        return


async def _run_qwen_batch(
    *,
    python_path: Path,
    runner_path: Path,
    request_path: Path,
    response_path: Path,
    timeout_seconds: float,
) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        str(python_path),
        str(runner_path),
        "--request",
        str(request_path),
        "--response",
        str(response_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        await _terminate_qwen_process(proc)
        raise RuntimeError(f"Qwen TTS 超时（>{timeout_seconds:.1f}s）") from exc

    stdout_text = stdout.decode("utf-8", errors="ignore").strip()
    stderr_text = stderr.decode("utf-8", errors="ignore").strip()
    if proc.returncode != 0:
        detail = stderr_text or stdout_text or f"exit={proc.returncode}"
        raise RuntimeError(f"Qwen TTS 失败: {detail[-1200:]}")
    return stdout_text, stderr_text


class QwenTtsProvider(TtsProvider):
    provider_name = "qwen"

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

        python_path = _resolve_qwen_python_path()
        runner_path = _resolve_qwen_runner_path()
        timeout_seconds = max(get_env_float("QWEN_TTS_TIMEOUT_SECONDS", 900.0), 5.0)
        request_payload = _build_qwen_batch_request(requests, context)
        if not request_payload["items"]:
            logger.warning("Qwen TTS 没有可生成的有效文本段")
            return TtsSynthesisBatchResult(
                requests=requests,
                success_map={},
                provider_name=self.provider_name,
            )

        request_path = context.work_dir / "qwen_tts_request.json"
        response_path = context.work_dir / "qwen_tts_response.json"
        request_path.write_text(
            json.dumps(request_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Qwen TTS 配置: model=%s, segments=%s, python=%s",
            request_payload["model_id"],
            len(request_payload["items"]),
            python_path,
        )
        stdout_text, stderr_text = await _run_qwen_batch(
            python_path=python_path,
            runner_path=runner_path,
            request_path=request_path,
            response_path=response_path,
            timeout_seconds=timeout_seconds,
        )
        if stdout_text:
            logger.info("Qwen TTS 输出: %s", stdout_text[-500:])
        if stderr_text:
            logger.warning("Qwen TTS stderr: %s", stderr_text[-500:])
        if not response_path.exists():
            raise RuntimeError(f"Qwen TTS 未产出响应文件: {response_path}")

        response_payload = json.loads(response_path.read_text(encoding="utf-8"))
        for failure in response_payload.get("failures", []):
            logger.warning(
                "Qwen TTS 段 %s 失败: %s",
                failure.get("segment_index"),
                failure.get("error", ""),
            )

        success_map: dict[int, TtsSynthesisResult] = {}
        for item in response_payload.get("results", []):
            segment_index = int(item["segment_index"])
            audio_path = Path(item["audio_path"])
            if not audio_path.exists() or audio_path.stat().st_size == 0:
                logger.warning("Qwen TTS 段 %s 输出缺失，跳过: %s", segment_index, audio_path)
                continue

            provider_metadata = {
                key: value
                for key, value in {
                    "speaker": item.get("speaker", ""),
                    "language": item.get("language", ""),
                }.items()
                if value
            }
            success_map[segment_index] = TtsSynthesisResult(
                audio_path=audio_path,
                raw_duration_seconds=float(item.get("raw_duration_seconds", 0.0)),
                provider_name=self.provider_name,
                timing_source="none",
                provider_metadata=provider_metadata,
            )

        return TtsSynthesisBatchResult(
            requests=requests,
            success_map=success_map,
            provider_name=self.provider_name,
        )
