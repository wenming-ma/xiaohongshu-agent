"""
图片压缩工具
用于审核前压缩图片，避免 413 错误
"""
import asyncio
import io
from pathlib import Path
from typing import Optional

from PIL import Image

from ..config.settings import ImageConfig


async def compress_image_for_review(
    image_path: Path,
    max_size_mb: Optional[float] = None
) -> bytes:
    """
    压缩图片用于审核

    策略：
    1. 转换为 JPEG 格式（有损压缩，效率高）
    2. 降低压缩质量
    3. 如仍过大，缩小尺寸

    Args:
        image_path: 原始图片路径
        max_size_mb: 最大大小（MB），默认使用配置

    Returns:
        压缩后的字节流（JPEG 格式）
    """
    if max_size_mb is None:
        max_size_mb = ImageConfig.MAX_REVIEW_SIZE_MB

    # 在线程池中执行 CPU 密集操作
    return await asyncio.to_thread(
        _compress_sync, image_path, max_size_mb
    )


def _compress_sync(image_path: Path, max_size_mb: float) -> bytes:
    """
    同步压缩实现

    Args:
        image_path: 图片路径
        max_size_mb: 最大大小（MB）

    Returns:
        压缩后的 JPEG 字节流
    """
    img = Image.open(image_path)

    # 转换为 RGB（处理 RGBA 透明通道）
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # 第一轮：尝试降低质量
    quality = ImageConfig.COMPRESS_QUALITY_START
    buffer = io.BytesIO()

    while quality >= ImageConfig.COMPRESS_QUALITY_MIN:
        buffer.seek(0)
        buffer.truncate()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        size_mb = len(buffer.getvalue()) / (1024 * 1024)

        if size_mb <= max_size_mb:
            print(f"      📦 图片压缩: {image_path.name} -> {size_mb:.2f}MB (质量: {quality})")
            return buffer.getvalue()

        quality -= ImageConfig.COMPRESS_QUALITY_STEP

    # 第二轮：缩小尺寸
    width, height = img.size
    current_size_mb = len(buffer.getvalue()) / (1024 * 1024)
    scale = (max_size_mb / current_size_mb) ** 0.5 * 0.9  # 留 10% 余量

    new_size = (int(width * scale), int(height * scale))
    img = img.resize(new_size, Image.LANCZOS)

    buffer.seek(0)
    buffer.truncate()
    img.save(buffer, format='JPEG', quality=ImageConfig.COMPRESS_QUALITY_MIN, optimize=True)

    final_size_mb = len(buffer.getvalue()) / (1024 * 1024)
    print(f"      📦 图片压缩+缩放: {image_path.name} -> {final_size_mb:.2f}MB ({new_size[0]}x{new_size[1]})")

    return buffer.getvalue()
