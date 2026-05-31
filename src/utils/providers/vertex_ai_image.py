"""Vertex AI image generation client."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Optional

from google.genai import types

from src.config.settings import APIConfig
from src.utils.logger import get_logger
from src.utils.providers.vertex_ai_common import build_vertex_client, is_retryable_vertex_error

logger = get_logger(__name__)


class VertexAIImageClient:
    """Generate images through Vertex AI Gemini image models."""

    _MAX_RETRIES = 12
    _semaphore: asyncio.Semaphore | None = None
    _semaphore_limit: int | None = None

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        limit = max(1, int(getattr(APIConfig, "VERTEX_AI_IMAGE_MAX_CONCURRENCY", 1)))
        if cls._semaphore is None or cls._semaphore_limit != limit:
            cls._semaphore = asyncio.Semaphore(limit)
            cls._semaphore_limit = limit
        return cls._semaphore

    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        model: Optional[str] = None,
        image_size: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> None:
        self.client, self.project, self.location = build_vertex_client(
            project=project,
            location=location,
        )
        self.model = model or APIConfig.VERTEX_AI_IMAGE_MODEL
        self.image_size = image_size or APIConfig.GEMINI_IMAGE_SIZE
        self.aspect_ratio = aspect_ratio

        logger.debug(
            "VertexAIImageClient initialized: project=%s, location=%s, model=%s, image_size=%s, aspect_ratio=%s",
            self.project,
            self.location,
            self.model,
            self.image_size,
            self.aspect_ratio,
        )

    @staticmethod
    def _build_parts(
        prompt: str,
        reference_images: list[tuple[str, Path]] | list[Path] | None = None,
    ) -> list[types.Part]:
        parts: list[types.Part] = []
        current_label: str | None = None

        for item in reference_images or []:
            if isinstance(item, tuple):
                label, ref_path = item
            else:
                label, ref_path = "reference", item
            if not ref_path.exists():
                continue
            if label != current_label:
                parts.append(types.Part.from_text(text=f"[Reference image: {label}]"))
                current_label = label
            mime = mimetypes.guess_type(str(ref_path))[0] or "image/jpeg"
            parts.append(types.Part.from_bytes(data=ref_path.read_bytes(), mime_type=mime))

        parts.append(types.Part.from_text(text=prompt))
        return parts

    @staticmethod
    def _extract_image_bytes(chunks: list[object]) -> tuple[bytes, str]:
        image_data: bytes | None = None
        mime_type = "image/png"

        for chunk in chunks:
            for candidate in getattr(chunk, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        image_data = inline_data.data
                        mime_type = getattr(inline_data, "mime_type", None) or mime_type
                    elif getattr(part, "text", None):
                        logger.debug("Vertex image generation returned text: %s", part.text[:200])

        if not image_data:
            raise ValueError("Vertex AI 未返回图片数据")
        return image_data, mime_type

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        image_size: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        max_retries: int = _MAX_RETRIES,
        reference_images: list[tuple[str, Path]] | list[Path] | None = None,
    ) -> Path:
        size = image_size or self.image_size
        ratio = aspect_ratio or self.aspect_ratio
        parts = self._build_parts(prompt, reference_images=reference_images)
        contents = [types.Content(role="user", parts=parts)]
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(
                image_size=size,
                aspect_ratio=ratio,
            ),
        )

        logger.info(
            "Generating image with Vertex AI: %s (model=%s, image_size=%s, aspect_ratio=%s)",
            output_path.name,
            self.model,
            size,
            ratio,
        )

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with self._get_semaphore():
                    chunks = await asyncio.to_thread(
                        lambda: list(
                            self.client.models.generate_content_stream(
                                model=self.model,
                                contents=contents,
                                config=config,
                            )
                        )
                    )
                image_bytes, mime_type = self._extract_image_bytes(chunks)
                ext = mimetypes.guess_extension(mime_type) or ".png"
                if output_path.suffix.lower() != ext.lower():
                    output_path = output_path.with_suffix(ext)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_bytes)
                logger.info("Vertex AI image saved: %s (%d KB)", output_path, len(image_bytes) // 1024)
                return output_path
            except Exception as exc:
                last_error = exc
                if not is_retryable_vertex_error(exc) or attempt >= max_retries - 1:
                    raise
                delay = min(5 * (attempt + 1), 60)
                logger.warning(
                    "Vertex AI image generation failed (%d/%d): %s, retrying in %ds",
                    attempt + 1,
                    max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("Vertex AI 图片生成失败")


async def generate_vertex_ai_image(
    prompt: str,
    output_path: Path,
    image_size: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    reference_images: list[tuple[str, Path]] | list[Path] | None = None,
) -> Path:
    client = VertexAIImageClient(aspect_ratio=aspect_ratio)
    return await client.generate_image(
        prompt=prompt,
        output_path=output_path,
        image_size=image_size,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
    )
