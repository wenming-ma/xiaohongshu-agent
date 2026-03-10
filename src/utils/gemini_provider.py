"""
Gemini 图片生成 API 客户端

通过 Google Gemini 原生 SDK 调用图片生成服务
"""
import mimetypes
from pathlib import Path
from typing import Optional

import httpx
from google import genai
from google.genai import types

from ..config.settings import APIConfig, RetryConfig, TimeoutConfig
from .logger import get_logger

logger = get_logger(__name__)


class GeminiImageClient:
    """
    Gemini 图片生成 API 客户端

    使用 Google Gemini 原生 SDK 直接调用
    支持多 API key 轮换，遇到速率限制自动切换
    """

    FALLBACK_API_KEYS: list[str] = APIConfig.GEMINI_FALLBACK_API_KEYS

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        image_size: Optional[str] = None,
    ):
        primary_key = api_key or APIConfig.GEMINI_API_KEY
        self.model = model or APIConfig.GEMINI_IMAGE_MODEL
        self.image_size = image_size or APIConfig.GEMINI_IMAGE_SIZE

        self.api_keys: list[str] = ([primary_key] if primary_key else []) + [
            k for k in self.FALLBACK_API_KEYS if k != primary_key
        ]
        if not self.api_keys:
            raise ValueError("GEMINI_API_KEY 环境变量未设置")
        self.current_key_index = 0

        self._init_client()

        logger.debug(
            "GeminiImageClient 初始化: model=%s, image_size=%s, api_keys=%d",
            self.model, self.image_size, len(self.api_keys)
        )

    def _init_client(self) -> None:
        """初始化 Gemini 客户端（使用当前 API key）"""
        timeout = TimeoutConfig.GEMINI_WAIT
        http_options = types.HttpOptions(
            timeout=timeout * 1000,
        )
        current_key = self.api_keys[self.current_key_index]
        self.client = genai.Client(api_key=current_key, http_options=http_options)
        logger.debug("使用 API key #%d", self.current_key_index + 1)

    _MAX_RETRIES = 12  # 总重试次数，每次失败循环轮换 key

    def _rotate_key(self) -> None:
        """循环轮换到下一个 API key"""
        old = self.current_key_index
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self._init_client()
        logger.info("Gemini key 轮换: #%d -> #%d", old + 1, self.current_key_index + 1)

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        image_size: Optional[str] = None,
        max_retries: int = _MAX_RETRIES,
    ) -> Path:
        """
        生成图片并保存到指定路径

        Args:
            prompt: 图片生成提示词
            output_path: 输出文件路径（包含文件名）
            image_size: 图片尺寸（可选），覆盖默认值
            max_retries: 最大重试次数

        Returns:
            保存的图片路径
        """
        size = image_size or self.image_size

        logger.info("开始生成图片: %s (size=%s)", output_path.name, size)
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
                    image_config=types.ImageConfig(image_size=size),
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
                        logger.debug("Gemini 返回文本: %s", part.text[:100])

                if not image_data:
                    raise ValueError("Gemini 未返回图片数据")

                if output_path.suffix.lower() != file_extension.lower():
                    output_path = output_path.with_suffix(file_extension)

                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_data)
                logger.info("图片已保存: %s (%d KB)", output_path, len(image_data) // 1024)
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
                    attempt + 1, max_retries, error_type, error_msg
                )
                self._rotate_key()

                if attempt < max_retries - 1:
                    import asyncio
                    delay = min(5 * (attempt + 1), 60)
                    logger.info("等待 %d 秒后重试...", delay)
                    await asyncio.sleep(delay)

        raise last_error or Exception("图片生成失败，已达最大重试次数")


async def generate_gemini_image(
    prompt: str,
    output_path: Path,
    image_size: Optional[str] = None,
) -> Path:
    """便捷函数：生成 Gemini 图片"""
    client = GeminiImageClient()
    return await client.generate_image(prompt, output_path, image_size=image_size)
