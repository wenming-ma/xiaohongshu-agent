"""
Gemini 图片去水印工具
基于反向 Alpha 混合算法，移植自 gemini-watermark-remover

原理：
- Gemini 添加水印: watermarked = α × logo + (1 - α) × original
- 反向还原公式: original = (watermarked - α × logo) / (1 - α)

参考: https://github.com/wenming-ma/gemini-watermark-remover
"""
import asyncio
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from .logger import get_logger

logger = get_logger(__name__)

# 常量定义
ALPHA_THRESHOLD = 0.002  # 忽略极小的 alpha 值（噪声）
MAX_ALPHA = 0.99         # 避免除以接近零的值
LOGO_VALUE = 255         # 白色水印的颜色值

# 资源路径
ASSETS_DIR = Path(__file__).parent.parent / "assets"
BG_48_PATH = ASSETS_DIR / "bg_48.png"
BG_96_PATH = ASSETS_DIR / "bg_96.png"


class GeminiWatermarkRemover:
    """
    Gemini 图片去水印器

    使用方式:
        remover = GeminiWatermarkRemover()
        remover.remove_watermark(image_path)  # 原地修改
        # 或
        remover.remove_watermark(image_path, output_path)  # 保存到新文件
    """

    def __init__(self):
        """初始化去水印器，预加载 alpha map"""
        self._alpha_maps: dict[int, np.ndarray] = {}
        self._load_alpha_maps()

    def _load_alpha_maps(self):
        """从背景图片加载 alpha map"""
        for size, path in [(48, BG_48_PATH), (96, BG_96_PATH)]:
            if not path.exists():
                logger.warning("Alpha map 文件不存在: %s", path)
                continue

            # 读取背景图片
            bg_img = Image.open(path).convert("RGB")
            bg_array = np.array(bg_img, dtype=np.float32)

            # 计算 alpha map: 取 RGB 最大值并归一化到 [0, 1]
            alpha_map = np.max(bg_array, axis=2) / 255.0
            self._alpha_maps[size] = alpha_map

            logger.debug("已加载 %dx%d alpha map", size, size)

    def _detect_watermark_config(self, width: int, height: int) -> dict:
        """
        根据图片尺寸检测水印配置

        Gemini 规则:
        - 宽高都 > 1024: 使用 96×96 水印，边距 64px
        - 其他情况: 使用 48×48 水印，边距 32px
        """
        if width > 1024 and height > 1024:
            return {
                "logo_size": 96,
                "margin_right": 64,
                "margin_bottom": 64
            }
        else:
            return {
                "logo_size": 48,
                "margin_right": 32,
                "margin_bottom": 32
            }

    def _calculate_watermark_position(self, width: int, height: int, config: dict) -> dict:
        """计算水印在图片中的位置"""
        logo_size = config["logo_size"]
        margin_right = config["margin_right"]
        margin_bottom = config["margin_bottom"]

        return {
            "x": width - margin_right - logo_size,
            "y": height - margin_bottom - logo_size,
            "width": logo_size,
            "height": logo_size
        }

    def _remove_watermark_from_array(
        self,
        img_array: np.ndarray,
        alpha_map: np.ndarray,
        position: dict
    ) -> np.ndarray:
        """
        使用反向 Alpha 混合从图片数组中移除水印

        Args:
            img_array: 图片数组 (H, W, C)，会被原地修改
            alpha_map: Alpha 通道数据 (logo_size, logo_size)
            position: 水印位置 {x, y, width, height}

        Returns:
            修改后的图片数组
        """
        x, y = position["x"], position["y"]
        w, h = position["width"], position["height"]

        # 提取水印区域
        watermark_region = img_array[y:y+h, x:x+w].astype(np.float32)

        # 创建 alpha 掩码，排除噪声值
        valid_mask = alpha_map >= ALPHA_THRESHOLD

        # 限制 alpha 值，避免除零
        alpha_clamped = np.clip(alpha_map, 0, MAX_ALPHA)
        one_minus_alpha = 1.0 - alpha_clamped

        # 对每个颜色通道应用反向 Alpha 混合
        for c in range(3):  # RGB
            channel = watermark_region[:, :, c]

            # 反向 Alpha 混合: original = (watermarked - α × logo) / (1 - α)
            original = (channel - alpha_clamped * LOGO_VALUE) / one_minus_alpha

            # 只在有效区域应用
            channel[valid_mask] = original[valid_mask]

        # 裁剪到 [0, 255] 并写回
        watermark_region = np.clip(watermark_region, 0, 255)
        img_array[y:y+h, x:x+w] = watermark_region.astype(np.uint8)

        return img_array

    def remove_watermark(
        self,
        image_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        从图片中移除 Gemini 水印

        Args:
            image_path: 输入图片路径
            output_path: 输出路径，为 None 时原地修改

        Returns:
            输出文件路径
        """
        image_path = Path(image_path)
        if output_path is None:
            output_path = image_path

        # 读取图片
        img = Image.open(image_path)
        width, height = img.size

        # 检测水印配置
        config = self._detect_watermark_config(width, height)
        logo_size = config["logo_size"]

        # 检查是否有对应的 alpha map
        if logo_size not in self._alpha_maps:
            logger.warning("未找到 %dx%d 的 alpha map，跳过去水印", logo_size, logo_size)
            return output_path

        alpha_map = self._alpha_maps[logo_size]
        position = self._calculate_watermark_position(width, height, config)

        # 转换为数组处理
        # 保持原始模式，但处理时使用 RGB
        original_mode = img.mode
        if img.mode == "RGBA":
            # 保存 alpha 通道
            alpha_channel = img.split()[3]
            img_rgb = img.convert("RGB")
        elif img.mode != "RGB":
            img_rgb = img.convert("RGB")
            alpha_channel = None
        else:
            img_rgb = img
            alpha_channel = None

        img_array = np.array(img_rgb)

        # 移除水印
        img_array = self._remove_watermark_from_array(img_array, alpha_map, position)

        # 转回 PIL Image
        result_img = Image.fromarray(img_array, mode="RGB")

        # 如果原图有 alpha 通道，恢复它
        if alpha_channel is not None:
            result_img = result_img.convert("RGBA")
            result_img.putalpha(alpha_channel)

        # 保存
        result_img.save(output_path)

        logger.info(
            "已移除水印: %s (%dx%d, logo=%d)",
            image_path.name, width, height, logo_size
        )

        return output_path

    async def remove_watermark_async(
        self,
        image_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """异步版本的去水印方法"""
        return await asyncio.to_thread(
            self.remove_watermark, image_path, output_path
        )


# 全局单例
_remover: Optional[GeminiWatermarkRemover] = None


def get_watermark_remover() -> GeminiWatermarkRemover:
    """获取去水印器单例"""
    global _remover
    if _remover is None:
        _remover = GeminiWatermarkRemover()
    return _remover


def remove_gemini_watermark(
    image_path: Path,
    output_path: Optional[Path] = None
) -> Path:
    """
    便捷函数：移除 Gemini 水印

    Args:
        image_path: 输入图片路径
        output_path: 输出路径，为 None 时原地修改

    Returns:
        输出文件路径
    """
    remover = get_watermark_remover()
    return remover.remove_watermark(image_path, output_path)


async def remove_gemini_watermark_async(
    image_path: Path,
    output_path: Optional[Path] = None
) -> Path:
    """异步版本的便捷函数"""
    remover = get_watermark_remover()
    return await remover.remove_watermark_async(image_path, output_path)
