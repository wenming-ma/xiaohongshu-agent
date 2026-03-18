"""
图片后处理管线 - 降低 AI 检测标记

4阶段处理:
1. 元数据清洗 - 去除 C2PA/EXIF/XMP/IPTC
2. 相机噪声模拟 - 对抗像素统计检测
3. 微几何变换 - 对抗频域指纹检测
4. JPEG 重编码 - 破坏残余特征
"""
import asyncio
import random
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from ..config.settings import SanitizerConfig
from .logger import get_logger

logger = get_logger(__name__)


class ImageSanitizer:
    """图片后处理管线 - 降低 AI 检测标记"""

    async def sanitize(self, image_path: Path, output_path: Optional[Path] = None) -> Path:
        """
        主入口：对图片执行完整的后处理管线

        Args:
            image_path: 输入图片路径
            output_path: 输出路径，为 None 时基于原路径生成 .jpg

        Returns:
            处理后的图片路径
        """
        if not SanitizerConfig.ENABLED:
            logger.debug("图片后处理管线已禁用，跳过")
            return image_path

        return await asyncio.to_thread(self._sanitize_sync, image_path, output_path)

    def _sanitize_sync(self, image_path: Path, output_path: Optional[Path] = None) -> Path:
        """同步执行4阶段管线"""
        if output_path is None:
            output_path = image_path.with_suffix(".jpg")

        img = Image.open(image_path).convert("RGB")
        original_size = img.size
        logger.info("开始图片后处理: %s (%dx%d)", image_path.name, *original_size)

        # Stage 1: 元数据清洗
        img = self._strip_metadata(img)

        # Stage 2: 相机噪声模拟
        img = self._add_camera_noise(img)

        # Stage 3: 微几何变换
        img = self._micro_transform(img, original_size)

        # Stage 4: JPEG 重编码
        self._save_jpeg(img, output_path)

        # Stage 5: 验证 - 扫描输出文件确认 AI 标记已清除
        self._verify_clean(output_path)

        # 如果输出路径不同于输入路径，且输入文件还在，删除原始文件
        if output_path != image_path and image_path.exists() and output_path.exists():
            image_path.unlink()
            logger.debug("已删除原始文件: %s", image_path.name)

        logger.info("图片后处理完成: %s", output_path.name)
        return output_path

    def _strip_metadata(self, img: Image.Image) -> Image.Image:
        """Stage 1: 元数据清洗 - 通过像素重建丢弃所有非像素数据"""
        pixels = list(img.getdata())
        clean = Image.new(img.mode, img.size)
        clean.putdata(pixels)
        logger.debug("Stage 1: 元数据已清洗")
        return clean

    def _add_camera_noise(self, img: Image.Image) -> Image.Image:
        """Stage 2: 相机噪声模拟 - 模拟 CMOS 传感器噪声"""
        arr = np.array(img, dtype=np.float64)

        # 散粒噪声 (Poisson) - 信号依赖
        gain = SanitizerConfig.SHOT_NOISE_GAIN
        normalized = np.clip(arr / 255.0, 1e-10, 1.0)
        shot_noise = np.random.poisson(normalized * gain).astype(np.float64) / gain * 255.0 - arr

        # 读取噪声 (Gaussian) - 信号无关
        sigma = SanitizerConfig.READ_NOISE_SIGMA
        read_noise = np.random.normal(0, sigma, arr.shape)

        # 混合噪声
        blend = SanitizerConfig.NOISE_BLEND
        noisy = arr + blend * (shot_noise + read_noise)
        noisy = np.clip(noisy, 0, 255).astype(np.uint8)

        logger.debug("Stage 2: 相机噪声已添加 (gain=%.1f, sigma=%.1f, blend=%.2f)", gain, sigma, blend)
        return Image.fromarray(noisy, mode="RGB")

    def _micro_transform(self, img: Image.Image, original_size: tuple[int, int]) -> Image.Image:
        """Stage 3: 微几何变换 - 破坏频域指纹"""
        w, h = img.size

        # 微旋转
        max_deg = SanitizerConfig.ROTATION_MAX_DEG
        angle = random.uniform(-max_deg, max_deg)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)

        # 裁切黑边 - 旋转后图片变大，裁切回原始尺寸
        new_w, new_h = img.size
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        img = img.crop((left, top, left + w, top + h))

        # 微缩放
        scale_range = SanitizerConfig.SCALE_RANGE
        scale = random.uniform(1.0 - scale_range, 1.0 + scale_range)
        scaled_w = int(w * scale)
        scaled_h = int(h * scale)
        img = img.resize((scaled_w, scaled_h), Image.BICUBIC)

        # 恢复到原始尺寸
        if (scaled_w, scaled_h) != original_size:
            img = img.resize(original_size, Image.BICUBIC)

        logger.debug("Stage 3: 微几何变换 (angle=%.2f°, scale=%.3f)", angle, scale)
        return img

    def _save_jpeg(self, img: Image.Image, output_path: Path) -> None:
        """Stage 4: JPEG 重编码"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        quality = SanitizerConfig.JPEG_QUALITY
        img.save(output_path, format="JPEG", quality=quality, optimize=True)
        size_kb = output_path.stat().st_size // 1024
        logger.debug("Stage 4: JPEG 重编码 (quality=%d, size=%dKB)", quality, size_kb)

    # 已知 AI 来源标记关键字（小写匹配）
    _AI_MARKER_KEYWORDS = [
        b"c2pa",
        b"synthid",
        b"trainedalgorithmicmedia",
        b"digitalsourcetype",
        b"jumbf",
    ]

    def _verify_clean(self, file_path: Path) -> None:
        """Stage 5: 扫描输出文件字节，确认 AI 来源标记已被清除"""
        raw = file_path.read_bytes()
        raw_lower = raw.lower()
        found = [kw.decode() for kw in self._AI_MARKER_KEYWORDS if kw in raw_lower]
        if found:
            logger.warning("输出文件仍包含 AI 标记: %s -> %s", file_path.name, ", ".join(found))
        else:
            logger.debug("Stage 5: 验证通过，未检测到已知 AI 标记")


# 全局单例
_sanitizer: Optional[ImageSanitizer] = None


def get_sanitizer() -> ImageSanitizer:
    """获取 sanitizer 单例"""
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = ImageSanitizer()
    return _sanitizer


async def sanitize_image(image_path: Path, output_path: Optional[Path] = None) -> Path:
    """便捷函数：对图片执行后处理管线"""
    sanitizer = get_sanitizer()
    return await sanitizer.sanitize(image_path, output_path)
