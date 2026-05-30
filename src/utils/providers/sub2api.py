"""
Sub2API 视觉 Provider

用途：
- 图片理解 / 审核：通过 OpenAI-compatible Responses API 返回 pydantic-ai Model
- 图片生成：通过 OpenAI-compatible Responses API 的 image_generation tool 生成图片

该 provider 独立于现有 openai.py，避免影响普通文本链路。
其中：
- 图片理解 / 审核默认使用多模态模型
- 图片生成默认使用专用图片模型
"""
from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING, TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - tested via monkeypatch
    AsyncOpenAI = None  # type: ignore[assignment]

try:
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider
except ImportError:  # pragma: no cover - tested via monkeypatch
    OpenAIResponsesModel = None  # type: ignore[assignment]
    OpenAIProvider = None  # type: ignore[assignment]

from src.config.settings import APIConfig, TimeoutConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from openai import AsyncOpenAI as AsyncOpenAIType
    from pydantic_ai.models.openai import OpenAIResponsesModel as OpenAIResponsesModelType
    from pydantic_ai.providers.openai import OpenAIProvider as OpenAIProviderType

_shared_provider: "OpenAIProviderType | None" = None
StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)

_RETRYABLE_KEYWORDS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "rate",
    "limit",
    "quota",
    "timeout",
    "unavailable",
    "overloaded",
    "connection",
    "disconnected",
)

_ASPECT_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "3:4": "1024x1536",
    "4:5": "1024x1536",
    "9:16": "1024x1536",
    "16:9": "1536x1024",
    "4:3": "1536x1024",
    "3:2": "1536x1024",
}


def _normalize_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    elif path != "/v1":
        path = f"{path}/v1" if not path.endswith("/v1") else path
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _get_api_key() -> str:
    api_key = os.getenv("SUB2API_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        load_dotenv()
        api_key = os.getenv("SUB2API_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("SUB2API_API_KEY / OPENAI_API_KEY 环境变量未设置")
    return api_key


def _get_base_url() -> str:
    base_url = os.getenv("SUB2API_BASE_URL") or os.getenv("OPENAI_BASE_URL") or APIConfig.OPENAI_BASE_URL
    if not base_url:
        raise ValueError("SUB2API_BASE_URL / OPENAI_BASE_URL 环境变量未设置")
    return _normalize_base_url(base_url)


def _get_default_model() -> str:
    return os.getenv("SUB2API_MODEL") or APIConfig.OPENAI_MODEL


def _get_vision_model() -> str:
    return os.getenv("SUB2API_VISION_MODEL") or _get_default_model()


def _get_image_model() -> str:
    return os.getenv("SUB2API_IMAGE_MODEL") or os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-2"


def _get_reasoning_effort() -> str:
    return os.getenv("SUB2API_REASONING_EFFORT", "xhigh")


def _responses_model_settings() -> dict[str, object]:
    return {
        "openai_reasoning_effort": _get_reasoning_effort(),
        # 我们的 message history 有处理器，关闭 reasoning ids 更稳。
        "openai_send_reasoning_ids": False,
        "openai_previous_response_id": "auto",
        "openai_truncation": "auto",
    }


def _build_async_client() -> AsyncOpenAI:
    if AsyncOpenAI is None:
        raise ImportError("缺少 openai 依赖，无法初始化 Sub2API provider")
    return AsyncOpenAI(
        api_key=_get_api_key(),
        base_url=_get_base_url(),
        timeout=float(TimeoutConfig.GEMINI_WAIT),
        # 禁用 SDK 级自动重试，避免与 provider 自己的重试策略叠加。
        max_retries=0,
    )


def get_sub2api_model(model_name: str | None = None) -> OpenAIResponsesModel:
    """
    获取 Sub2API 的 OpenAI-compatible Responses model。

    默认用于视觉理解、OCR、图片审核等多模态文本输出场景。
    """
    if OpenAIProvider is None or OpenAIResponsesModel is None:
        raise ImportError("缺少 pydantic-ai OpenAI 依赖，无法初始化 Sub2API model")
    global _shared_provider
    if _shared_provider is None:
        _shared_provider = OpenAIProvider(openai_client=_build_async_client())
        logger.info("Sub2API Provider 初始化完成: %s", _get_base_url())

    return OpenAIResponsesModel(
        model_name or _get_vision_model(),
        provider=_shared_provider,
        settings=_responses_model_settings(),
    )


def reset_provider() -> None:
    global _shared_provider
    _shared_provider = None
    logger.info("Sub2API Provider 已重置")


def _is_retryable_error(error: Exception) -> bool:
    module = type(error).__module__ or ""
    if module.startswith(("httpx", "httpcore", "openai")):
        return True
    return any(keyword in str(error).lower() for keyword in _RETRYABLE_KEYWORDS)


def _encode_image_as_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _resolve_image_size(image_size: Optional[str], aspect_ratio: Optional[str]) -> str:
    if image_size in {"1024x1024", "1024x1536", "1536x1024", "auto"}:
        return image_size
    if aspect_ratio:
        return _ASPECT_RATIO_TO_SIZE.get(aspect_ratio, "auto")
    return "auto"


def _resolve_media_type(path: Path, media_type: str | None = None) -> str:
    return media_type or mimetypes.guess_type(str(path))[0] or "image/jpeg"


def _encode_image_bytes_as_data_url(image_bytes: bytes, media_type: str) -> str:
    payload = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _extract_output_text(response) -> str:
    texts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", []) or []:
            if getattr(part, "type", None) == "output_text" and getattr(part, "text", None):
                texts.append(part.text)
    if texts:
        return "\n".join(texts).strip()
    raise ValueError("Sub2API 未返回文本内容")


def _build_json_schema_payload(response_model: type[BaseModel]) -> dict[str, object]:
    return {
        "format": {
            "type": "json_schema",
            "name": response_model.__name__.lower(),
            "schema": response_model.model_json_schema(),
            "strict": True,
        }
    }


class Sub2APIVisionClient:
    """通过 Sub2API 的 Responses API 执行读图 / OCR / 图片审核。"""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        detail: str = "high",
    ) -> None:
        self.model = model or _get_vision_model()
        self.detail = detail
        self.client = _build_async_client()

        logger.debug(
            "Sub2APIVisionClient 初始化: model=%s, detail=%s",
            self.model,
            self.detail,
        )

    async def _create_response(
        self,
        *,
        request_input: list[dict[str, object]],
        response_model: type[StructuredResponseT] | None = None,
    ) -> str | StructuredResponseT:
        create_kwargs: dict[str, object] = {
            "model": self.model,
            "input": request_input,
            "store": False,
            "reasoning": {"effort": _get_reasoning_effort()},
        }
        if response_model is not None:
            create_kwargs["text"] = _build_json_schema_payload(response_model)

        response = await self.client.responses.create(**create_kwargs)
        output_text = _extract_output_text(response)
        if response_model is None:
            return output_text
        return response_model.model_validate_json(output_text)

    @staticmethod
    def _build_request_input(
        *,
        prompt: str,
        image_url: str,
        detail: str,
        system_prompt: str | None,
    ) -> list[dict[str, object]]:
        request_input: list[dict[str, object]] = []
        if system_prompt:
            request_input.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                }
            )
        request_input.append(
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "detail": detail,
                        "image_url": image_url,
                    },
                ],
            }
        )
        return request_input

    async def analyze_image(
        self,
        *,
        image_path: Path,
        prompt: str,
        media_type: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        return await self.analyze_image_bytes(
            image_bytes=image_path.read_bytes(),
            prompt=prompt,
            media_type=_resolve_media_type(image_path, media_type),
            system_prompt=system_prompt,
        )

    async def analyze_image_bytes(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        media_type: str = "image/jpeg",
        system_prompt: str | None = None,
    ) -> str:
        request_input = self._build_request_input(
            prompt=prompt,
            image_url=_encode_image_bytes_as_data_url(image_bytes, media_type),
            detail=self.detail,
            system_prompt=system_prompt,
        )
        return await self._create_response(request_input=request_input)

    async def analyze_image_structured(
        self,
        *,
        image_path: Path,
        prompt: str,
        response_model: type[StructuredResponseT],
        media_type: str | None = None,
        system_prompt: str | None = None,
    ) -> StructuredResponseT:
        return await self.analyze_image_bytes_structured(
            image_bytes=image_path.read_bytes(),
            prompt=prompt,
            response_model=response_model,
            media_type=_resolve_media_type(image_path, media_type),
            system_prompt=system_prompt,
        )

    async def analyze_image_bytes_structured(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        response_model: type[StructuredResponseT],
        media_type: str = "image/jpeg",
        system_prompt: str | None = None,
    ) -> StructuredResponseT:
        request_input = self._build_request_input(
            prompt=prompt,
            image_url=_encode_image_bytes_as_data_url(image_bytes, media_type),
            detail=self.detail,
            system_prompt=system_prompt,
        )
        return await self._create_response(
            request_input=request_input,
            response_model=response_model,
        )


class Sub2APIImageClient:
    """通过 Sub2API 的 Responses API image_generation tool 生成图片。"""

    _MAX_RETRIES = 8

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        quality: str = "high",
        output_format: str = "png",
    ) -> None:
        self.model = model or _get_image_model()
        self.aspect_ratio = aspect_ratio
        self.quality = quality
        self.output_format = output_format
        self.client = _build_async_client()

        logger.debug(
            "Sub2APIImageClient 初始化: model=%s, aspect_ratio=%s, output_format=%s",
            self.model,
            self.aspect_ratio,
            self.output_format,
        )

    def _build_input(
        self,
        prompt: str,
        reference_images: list[tuple[str, Path]] | list[Path] | None = None,
    ) -> list[dict[str, object]]:
        content: list[dict[str, object]] = []
        if reference_images:
            for item in reference_images:
                if isinstance(item, tuple):
                    label, path = item
                else:
                    label, path = "reference", item
                if not path.exists():
                    continue
                content.append({"type": "input_text", "text": f"[Reference image: {label}]"})
                content.append(
                    {
                        "type": "input_image",
                        "image_url": _encode_image_as_data_url(path),
                        "detail": "high",
                    }
                )
        content.append({"type": "input_text", "text": prompt})
        return [{"role": "user", "content": content}]

    @staticmethod
    def _extract_image_bytes(response) -> bytes:
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "image_generation_call":
                continue
            if getattr(item, "result", None):
                return base64.b64decode(item.result)
        raise ValueError("Sub2API 未返回图片数据")

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        image_size: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        max_retries: int = _MAX_RETRIES,
        reference_images: list[tuple[str, Path]] | list[Path] | None = None,
    ) -> Path:
        size = _resolve_image_size(image_size, aspect_ratio or self.aspect_ratio)
        request_input = self._build_input(prompt, reference_images=reference_images)

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    input=request_input,
                    store=False,
                    tools=[
                        {
                            "type": "image_generation",
                            "size": size,
                            "quality": self.quality,
                            "output_format": self.output_format,
                            "background": "opaque",
                        }
                    ],
                    tool_choice={"type": "image_generation"},
                )
                image_bytes = self._extract_image_bytes(response)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_bytes)
                logger.info("图片已保存: %s (%d KB)", output_path, len(image_bytes) // 1024)
                return output_path
            except Exception as exc:
                last_error = exc
                if not _is_retryable_error(exc) or attempt >= max_retries - 1:
                    raise
                delay = min(5 * (attempt + 1), 60)
                logger.warning(
                    "Sub2API 图片生成失败 (%d/%d): %s，%ds 后重试",
                    attempt + 1,
                    max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Sub2API 图片生成失败")


async def generate_sub2api_image(
    prompt: str,
    output_path: Path,
    image_size: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    reference_images: list[tuple[str, Path]] | list[Path] | None = None,
) -> Path:
    client = Sub2APIImageClient(aspect_ratio=aspect_ratio)
    return await client.generate_image(
        prompt=prompt,
        output_path=output_path,
        image_size=image_size,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
    )
