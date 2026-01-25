"""
Gemini 图片生成 API 客户端

通过 OpenAI 兼容 API 调用 Gemini 图片生成服务
"""
import base64
import re
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from ...config.settings import APIConfig, RetryConfig
from ...utils.logger import get_logger

logger = get_logger(__name__)


class GeminiImageClient:
    """
    Gemini 图片生成 API 客户端

    使用 OpenAI 兼容 API 格式调用本地代理服务
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        size: Optional[str] = None,
    ):
        """
        初始化客户端

        Args:
            base_url: API 基础 URL，默认从配置读取
            api_key: API 密钥，默认从配置读取
            model: 模型名称，默认从配置读取
            size: 图片尺寸，默认从配置读取
        """
        self.base_url = base_url or APIConfig.GEMINI_IMAGE_BASE_URL
        self.api_key = api_key or APIConfig.GEMINI_IMAGE_API_KEY
        self.model = model or APIConfig.GEMINI_IMAGE_MODEL
        self.size = size or APIConfig.GEMINI_IMAGE_SIZE

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

        logger.debug(
            "GeminiImageClient 初始化: base_url=%s, model=%s, size=%s",
            self.base_url, self.model, self.size
        )

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        size: Optional[str] = None,
        max_retries: int = RetryConfig.MAX_RETRIES,
    ) -> Path:
        """
        生成图片并保存到指定路径

        Args:
            prompt: 图片生成提示词
            output_path: 输出文件路径（包含文件名）
            size: 图片尺寸（可选），覆盖默认值
            max_retries: 最大重试次数

        Returns:
            保存的图片路径

        Raises:
            Exception: 生成或保存失败
        """
        image_size = size or self.size

        logger.info("开始生成图片: %s", output_path.name)
        logger.debug("提示词: %s...", prompt[:100])

        last_error = None
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    extra_body={"size": image_size},
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }]
                )

                content = response.choices[0].message.content

                if not content:
                    raise ValueError("API 返回空内容")

                # 解析响应内容，提取图片数据
                image_data = self._extract_image_data(content)

                if image_data:
                    # 保存图片
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(image_data)
                    logger.info("图片已保存: %s (%d KB)", output_path, len(image_data) // 1024)
                    return output_path
                else:
                    raise ValueError(f"无法从响应中提取图片数据: {content[:200]}...")

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 检查是否是限流错误
                if "limited" in error_msg.lower() or "429" in error_msg:
                    # 提取等待时间
                    wait_match = re.search(r'wait\s+(\d+)s', error_msg)
                    if wait_match:
                        wait_seconds = int(wait_match.group(1))
                        logger.warning(
                            "API 限流，需要等待 %d 秒 (约 %d 分钟)",
                            wait_seconds, wait_seconds // 60
                        )
                    else:
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

    def _extract_image_data(self, content: str) -> Optional[bytes]:
        """
        从 API 响应中提取图片数据

        支持的格式：
        1. Base64 编码的图片数据 (data:image/png;base64,...)
        2. 纯 Base64 字符串
        3. Markdown 图片格式 ![...](data:image/...)

        Args:
            content: API 响应内容

        Returns:
            图片二进制数据，如果无法提取则返回 None
        """
        # 尝试匹配 data URL 格式
        data_url_pattern = r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)'
        match = re.search(data_url_pattern, content)
        if match:
            try:
                return base64.b64decode(match.group(1))
            except Exception as e:
                logger.warning("Base64 解码失败: %s", e)

        # 尝试匹配 Markdown 图片格式
        md_pattern = r'!\[.*?\]\((data:image/[^)]+)\)'
        match = re.search(md_pattern, content)
        if match:
            data_url = match.group(1)
            inner_match = re.search(data_url_pattern, data_url)
            if inner_match:
                try:
                    return base64.b64decode(inner_match.group(1))
                except Exception as e:
                    logger.warning("Markdown 图片 Base64 解码失败: %s", e)

        # 尝试将整个内容作为 Base64 解码
        # 先清理可能的空白字符
        clean_content = content.strip()
        if len(clean_content) > 100:  # 合理长度的 Base64
            try:
                data = base64.b64decode(clean_content)
                # 检查是否是有效的 PNG 或 JPEG
                if data[:4] == b'\x89PNG' or data[:2] == b'\xff\xd8':
                    return data
            except Exception:
                pass

        return None


# 便捷函数
async def generate_gemini_image(
    prompt: str,
    output_path: Path,
    size: Optional[str] = None,
) -> Path:
    """
    便捷函数：生成 Gemini 图片

    Args:
        prompt: 图片生成提示词
        output_path: 输出文件路径
        size: 图片尺寸（可选）

    Returns:
        保存的图片路径
    """
    client = GeminiImageClient()
    return await client.generate_image(prompt, output_path, size=size)
