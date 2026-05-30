"""Vertex AI multimodal vision client."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Optional, TypeVar

from google.genai import types
from pydantic import BaseModel

from src.config.settings import APIConfig
from src.utils.logger import get_logger
from src.utils.providers.vertex_ai_common import build_vertex_client, is_retryable_vertex_error

logger = get_logger(__name__)

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


class VertexAIVisionClient:
    """Analyze local images using a Vertex AI multimodal text model."""

    _MAX_RETRIES = 8

    def __init__(
        self,
        *,
        project: Optional[str] = None,
        location: Optional[str] = None,
        model: Optional[str] = None,
        detail: str = "high",
    ) -> None:
        self.client, self.project, self.location = build_vertex_client(
            project=project,
            location=location,
        )
        self.model = model or APIConfig.VERTEX_AI_VISION_MODEL
        self.detail = detail

        logger.debug(
            "VertexAIVisionClient initialized: project=%s, location=%s, model=%s, detail=%s",
            self.project,
            self.location,
            self.model,
            self.detail,
        )

    @staticmethod
    def _build_contents(*, prompt: str, image_bytes: bytes, media_type: str) -> list[types.Content]:
        return [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                ],
            )
        ]

    @staticmethod
    def _extract_text(response: object) -> str:
        text = getattr(response, "text", None)
        if text:
            return text.strip()

        texts: list[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                if getattr(part, "text", None):
                    texts.append(part.text)
        if texts:
            return "\n".join(texts).strip()
        raise ValueError("Vertex AI 未返回文本内容")

    async def _generate(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        media_type: str,
        system_prompt: str | None,
        response_model: type[StructuredResponseT] | None,
    ) -> str | StructuredResponseT:
        contents = self._build_contents(prompt=prompt, image_bytes=image_bytes, media_type=media_type)
        config_kwargs: dict[str, object] = {}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if response_model is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_model
        config = types.GenerateContentConfig(**config_kwargs)

        last_error: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                response = await asyncio.to_thread(
                    lambda: self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                )
                output_text = self._extract_text(response)
                if response_model is None:
                    return output_text
                return response_model.model_validate_json(output_text)
            except Exception as exc:
                last_error = exc
                if not is_retryable_vertex_error(exc) or attempt >= self._MAX_RETRIES - 1:
                    raise
                delay = min(5 * (attempt + 1), 60)
                logger.warning(
                    "Vertex AI vision request failed (%d/%d): %s, retrying in %ds",
                    attempt + 1,
                    self._MAX_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Vertex AI 读图失败")

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
            media_type=media_type or mimetypes.guess_type(str(image_path))[0] or "image/jpeg",
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
        return await self._generate(
            prompt=prompt,
            image_bytes=image_bytes,
            media_type=media_type,
            system_prompt=system_prompt,
            response_model=None,
        )

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
            media_type=media_type or mimetypes.guess_type(str(image_path))[0] or "image/jpeg",
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
        result = await self._generate(
            prompt=prompt,
            image_bytes=image_bytes,
            media_type=media_type,
            system_prompt=system_prompt,
            response_model=response_model,
        )
        if isinstance(result, str):  # pragma: no cover - defensive only
            raise TypeError("Expected structured response, got plain text")
        return result
