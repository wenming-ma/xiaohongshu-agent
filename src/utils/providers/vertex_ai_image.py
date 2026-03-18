"""
Vertex AI Gemini 图片生成 API 客户端

通过 Google Gen AI SDK (vertexai=True) 调用 Vertex AI 端点
使用 Application Default Credentials 认证
"""
import mimetypes
from pathlib import Path
from typing import Optional

import httpx
from google import genai
from google.genai import types

from ...config.settings import APIConfig, RetryConfig, SanitizerConfig, TimeoutConfig
from ..image_sanitizer import sanitize_image
from ..logger import get_logger
from ..watermark_remover import remove_gemini_watermark

logger = get_logger(__name__)


class VertexAIImageClient:
    """
    Vertex AI Gemini 图片生成客户端

    通过 Vertex AI 端点调用，使用 Application Default Credentials 认证
    需设置 VERTEX_AI_PROJECT_ID 环境变量
    """

    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        model: Optional[str] = None,
        image_size: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ):
        self.project = project or APIConfig.VERTEX_AI_PROJECT_ID
        if not self.project:
            raise ValueError("VERTEX_AI_PROJECT_ID 环境变量未设置")

        self.location = location or APIConfig.VERTEX_AI_LOCATION
        self.model = model or APIConfig.VERTEX_AI_IMAGE_MODEL
        self.image_size = image_size or APIConfig.GEMINI_IMAGE_SIZE
        self.aspect_ratio = aspect_ratio

        timeout = TimeoutConfig.GEMINI_WAIT
        http_options = types.HttpOptions(timeout=timeout * 1000)
        self.client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
            http_options=http_options,
        )

        logger.debug(
            "VertexAIImageClient 初始化: project=%s, location=%s, model=%s, image_size=%s, aspect_ratio=%s",
            self.project, self.location, self.model, self.image_size, self.aspect_ratio,
        )

    _MAX_RETRIES = 12

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        image_size: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        max_retries: int = _MAX_RETRIES,
    ) -> Path:
        """
        生成图片并保存到指定路径

        Args:
            prompt: 图片生成提示词
            output_path: 输出文件路径（包含文件名）
            image_size: 图片尺寸（可选），覆盖默认值
            aspect_ratio: 图片比例（可选），覆盖默认值
            max_retries: 最大重试次数

        Returns:
            保存的图片路径
        """
        size = image_size or self.image_size
        ratio = aspect_ratio or self.aspect_ratio

        logger.info("开始生成图片 (Vertex AI): %s (size=%s, aspect_ratio=%s)", output_path.name, size, ratio)
        logger.debug("提示词: %s...", prompt[:100])

        last_error = None
        for attempt in range(max_retries):
            try:
                contents = [
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt)],
                    ),
                ]

                generate_content_config = types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=types.ImageConfig(
                        image_size=size,
                        aspect_ratio=ratio,
                    ),
                )

                image_data = None
                file_extension = ".png"

                for chunk in self.client.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=generate_content_config,
                ):
                    if (
                        chunk.candidates is None
                        or chunk.candidates[0].content is None
                        or chunk.candidates[0].content.parts is None
                    ):
                        continue

                    part = chunk.candidates[0].content.parts[0]
                    if part.inline_data and part.inline_data.data:
                        image_data = part.inline_data.data
                        ext = mimetypes.guess_extension(part.inline_data.mime_type)
                        if ext:
                            file_extension = ext
                    elif hasattr(part, 'text') and part.text:
                        logger.debug("Vertex AI 返回文本: %s", part.text[:100])

                if not image_data:
                    raise ValueError("Vertex AI 未返回图片数据")

                if output_path.suffix.lower() != file_extension.lower():
                    output_path = output_path.with_suffix(file_extension)

                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_data)
                logger.info("图片已保存: %s (%d KB)", output_path, len(image_data) // 1024)

                # 去除可见水印
                try:
                    remove_gemini_watermark(output_path)
                    logger.debug("可见水印已去除: %s", output_path.name)
                except Exception as e:
                    logger.warning("去可见水印失败，继续处理: %s", e)

                # AI 检测标记后处理
                if SanitizerConfig.ENABLED:
                    try:
                        output_path = await sanitize_image(output_path)
                    except Exception as e:
                        logger.warning("图片后处理失败，使用原始文件: %s", e)

                return output_path

            except Exception as e:
                last_error = e
                error_msg = str(e)
                error_type = type(e).__name__

                is_retryable = any([
                    "limited" in error_msg.lower(),
                    "429" in error_msg,
                    "quota" in error_msg.lower(),
                    "503" in error_msg,
                    "overloaded" in error_msg.lower(),
                    "unavailable" in error_msg.lower(),
                    isinstance(e, (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)),
                    "disconnected" in error_msg.lower(),
                    "connection" in error_msg.lower(),
                    "timeout" in error_msg.lower(),
                ])

                if not is_retryable:
                    raise

                logger.warning(
                    "图片生成失败 (%d/%d): [%s] %s",
                    attempt + 1, max_retries, error_type, error_msg,
                )

                if attempt < max_retries - 1:
                    import asyncio
                    delay = min(5 * (attempt + 1), 60)
                    logger.info("等待 %d 秒后重试...", delay)
                    await asyncio.sleep(delay)

        raise last_error or Exception("图片生成失败，已达最大重试次数")


async def generate_vertex_ai_image(
    prompt: str,
    output_path: Path,
    image_size: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
) -> Path:
    """便捷函数：通过 Vertex AI 生成图片"""
    client = VertexAIImageClient()
    return await client.generate_image(
        prompt,
        output_path,
        image_size=image_size,
        aspect_ratio=aspect_ratio,
    )
