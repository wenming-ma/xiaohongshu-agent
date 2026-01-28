"""
Gemini 图片生成 API 客户端

通过 OpenAI Images API 调用 Gemini 图片生成服务
"""
import base64
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from ...config.settings import APIConfig, RetryConfig
from ...utils.logger import get_logger

logger = get_logger(__name__)


class GeminiImageClient:
    """
    Gemini 图片生成 API 客户端

    使用 OpenAI Images API 格式调用本地代理服务
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        size: Optional[str] = None,
        quality: Optional[str] = None,
    ):
        """
        初始化客户端

        Args:
            base_url: API 基础 URL，默认从配置读取
            api_key: API 密钥，默认从配置读取
            model: 模型名称，默认从配置读取
            size: 图片尺寸，默认从配置读取
            quality: 图片质量，"hd" (4K) | "medium" (2K) | "standard"，默认从配置读取
        """
        self.base_url = base_url or APIConfig.GEMINI_IMAGE_BASE_URL
        self.api_key = api_key or APIConfig.GEMINI_IMAGE_API_KEY
        self.model = model or APIConfig.GEMINI_IMAGE_MODEL
        self.size = size or APIConfig.GEMINI_IMAGE_SIZE
        self.quality = quality or APIConfig.GEMINI_IMAGE_QUALITY

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

        logger.debug(
            "GeminiImageClient 初始化: base_url=%s, model=%s, size=%s, quality=%s",
            self.base_url, self.model, self.size, self.quality
        )

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        max_retries: int = RetryConfig.MAX_RETRIES,
    ) -> Path:
        """
        生成图片并保存到指定路径

        Args:
            prompt: 图片生成提示词
            output_path: 输出文件路径（包含文件名）
            size: 图片尺寸（可选），覆盖默认值
            quality: 图片质量（可选），覆盖默认值
            max_retries: 最大重试次数

        Returns:
            保存的图片路径

        Raises:
            Exception: 生成或保存失败
        """
        image_size = size or self.size
        image_quality = quality or self.quality

        logger.info("开始生成图片: %s (size=%s, quality=%s)", output_path.name, image_size, image_quality)
        logger.debug("提示词: %s...", prompt[:100])

        last_error = None
        for attempt in range(max_retries):
            try:
                # 使用 OpenAI Images API (推荐方式)
                response = await self.client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    size=image_size,
                    quality=image_quality,
                    n=1,
                    response_format="b64_json"
                )

                # 解码 base64 图片数据
                image_data = base64.b64decode(response.data[0].b64_json)

                if not image_data:
                    raise ValueError("API 返回空图片数据")

                # 保存图片
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_data)
                logger.info("图片已保存: %s (%d KB)", output_path, len(image_data) // 1024)
                return output_path

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 检查是否是限流错误
                if "limited" in error_msg.lower() or "429" in error_msg:
                    logger.warning("API 限流: %s", error_msg)
                    raise  # 限流错误直接抛出，不重试

                logger.warning(
                    "图片生成失败 (尝试 %d/%d): %s",
                    attempt + 1, max_retries, error_msg
                )

                if attempt < max_retries - 1:
                    import asyncio
                    delay = min(2 ** attempt, 30)  # 指数退避，最多30秒
                    logger.info("等待 %d 秒后重试...", delay)
                    await asyncio.sleep(delay)

        raise last_error or Exception("图片生成失败，已达最大重试次数")


# 便捷函数
async def generate_gemini_image(
    prompt: str,
    output_path: Path,
    size: Optional[str] = None,
    quality: Optional[str] = None,
) -> Path:
    """
    便捷函数：生成 Gemini 图片

    Args:
        prompt: 图片生成提示词
        output_path: 输出文件路径
        size: 图片尺寸（可选）
        quality: 图片质量（可选），"hd" (4K) | "medium" (2K) | "standard"

    Returns:
        保存的图片路径
    """
    client = GeminiImageClient()
    return await client.generate_image(prompt, output_path, size=size, quality=quality)
