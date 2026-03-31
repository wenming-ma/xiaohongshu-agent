"""
Gemini 图片去水印工具 v2
移植自 GargantuaX/gemini-watermark-remover v1.0.9

核心改进:
- Gemini 官方尺寸目录，精确匹配水印配置
- 自适应模板匹配检测水印位置和大小
- 多次移除 + Alpha 增益校准
- 亚像素精细化 + 边缘清理
- 安全检查（近黑比例、纹理坍缩）

原理:
- Gemini 添加水印: watermarked = α × logo + (1 - α) × original
- 反向还原公式: original = (watermarked - α × logo) / (1 - α)

参考: https://github.com/GargantuaX/gemini-watermark-remover
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from ....utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
ALPHA_NOISE_FLOOR = 3.0 / 255.0  # 去除压缩引入的低级噪声
ALPHA_THRESHOLD = 0.002           # 激活信号阈值
MAX_ALPHA = 0.99                  # 避免除零
LOGO_VALUE = 255.0                # 白色水印颜色值
EPSILON = 1e-8

# 多次移除
DEFAULT_MAX_PASSES = 4
DEFAULT_RESIDUAL_THRESHOLD = 0.25
MAX_NEAR_BLACK_RATIO_INCREASE = 0.05
NEAR_BLACK_THRESHOLD = 5

# 自适应检测
ADAPTIVE_DEFAULT_THRESHOLD = 0.35

# 候选验证
VALIDATION_MIN_IMPROVEMENT = 0.08
VALIDATION_TARGET_RESIDUAL = 0.22
VALIDATION_MAX_GRADIENT_INCREASE = 0.04
STANDARD_FAST_PATH_RESIDUAL_THRESHOLD = 0.22
STANDARD_FAST_PATH_GRADIENT_THRESHOLD = 0.08

# Alpha 增益校准
RESIDUAL_RECALIBRATION_THRESHOLD = 0.5
MIN_SUPPRESSION_FOR_SKIP_RECALIBRATION = 0.18
MIN_RECALIBRATION_SCORE_DELTA = 0.18
ALPHA_GAIN_CANDIDATES = [
    1.05, 1.12, 1.2, 1.28, 1.36, 1.45, 1.52, 1.6, 1.7, 1.85, 2.0, 2.2, 2.4, 2.6,
]

# 亚像素精细化
OUTLINE_REFINEMENT_THRESHOLD = 0.42
OUTLINE_REFINEMENT_MIN_GAIN = 1.2
SUBPIXEL_REFINE_SHIFTS = [-0.25, 0.0, 0.25]
SUBPIXEL_REFINE_SCALES = [0.99, 1.0, 1.01]

# 水印信号分类阈值
STANDARD_DIRECT_MATCH_MIN_SPATIAL = 0.3
STANDARD_DIRECT_MATCH_MIN_GRADIENT = 0.12
STANDARD_STRONG_GRADIENT_MIN_SPATIAL = 0.295
STANDARD_STRONG_GRADIENT_MIN_GRADIENT = 0.45
ADAPTIVE_DIRECT_MATCH_MIN_CONFIDENCE = 0.5
ADAPTIVE_DIRECT_MATCH_MIN_SPATIAL = 0.45
ADAPTIVE_DIRECT_MATCH_MIN_GRADIENT = 0.12

# 纹理评估
TEXTURE_REFERENCE_MARGIN = 1
TEXTURE_STD_FLOOR_RATIO = 0.8

# 首次 pass 停止
FIRST_PASS_SIGN_FLIP_GRADIENT_THRESHOLD = 0.08
FIRST_PASS_SIGN_FLIP_MIN_GRADIENT_DROP = 0.2

# 资源路径
ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets"
BG_48_PATH = ASSETS_DIR / "bg_48.png"
BG_96_PATH = ASSETS_DIR / "bg_96.png"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class WatermarkConfig:
    logo_size: int
    margin_right: int
    margin_bottom: int


@dataclass
class WatermarkPosition:
    x: int
    y: int
    width: int
    height: int


@dataclass
class RegionScores:
    spatial_score: float
    gradient_score: float


# ---------------------------------------------------------------------------
# Gemini 官方尺寸目录
# ---------------------------------------------------------------------------
_WATERMARK_CONFIG_BY_TIER = {
    "0.5k": WatermarkConfig(48, 32, 32),
    "1k": WatermarkConfig(96, 64, 64),
    "2k": WatermarkConfig(96, 64, 64),
    "4k": WatermarkConfig(96, 64, 64),
}

_OFFICIAL_GEMINI_SIZES: list[tuple[str, str, str, int, int]] = [
    # (model, tier, ratio, width, height)
    # gemini-3.x-image 0.5k
    ("gemini-3.x", "0.5k", "1:1", 512, 512),
    ("gemini-3.x", "0.5k", "1:4", 256, 1024),
    ("gemini-3.x", "0.5k", "1:8", 192, 1536),
    ("gemini-3.x", "0.5k", "2:3", 424, 632),
    ("gemini-3.x", "0.5k", "3:2", 632, 424),
    ("gemini-3.x", "0.5k", "3:4", 448, 600),
    ("gemini-3.x", "0.5k", "4:1", 1024, 256),
    ("gemini-3.x", "0.5k", "4:3", 600, 448),
    ("gemini-3.x", "0.5k", "4:5", 464, 576),
    ("gemini-3.x", "0.5k", "5:4", 576, 464),
    ("gemini-3.x", "0.5k", "8:1", 1536, 192),
    ("gemini-3.x", "0.5k", "9:16", 384, 688),
    ("gemini-3.x", "0.5k", "16:9", 688, 384),
    ("gemini-3.x", "0.5k", "21:9", 792, 168),
    # gemini-3.x-image 1k
    ("gemini-3.x", "1k", "1:1", 1024, 1024),
    ("gemini-3.x", "1k", "1:4", 512, 2064),
    ("gemini-3.x", "1k", "1:8", 352, 2928),
    ("gemini-3.x", "1k", "2:3", 848, 1264),
    ("gemini-3.x", "1k", "3:2", 1264, 848),
    ("gemini-3.x", "1k", "3:4", 896, 1200),
    ("gemini-3.x", "1k", "4:1", 2064, 512),
    ("gemini-3.x", "1k", "4:3", 1200, 896),
    ("gemini-3.x", "1k", "4:5", 928, 1152),
    ("gemini-3.x", "1k", "5:4", 1152, 928),
    ("gemini-3.x", "1k", "8:1", 2928, 352),
    ("gemini-3.x", "1k", "9:16", 768, 1376),
    ("gemini-3.x", "1k", "16:9", 1376, 768),
    ("gemini-3.x", "1k", "16:9", 1408, 768),
    ("gemini-3.x", "1k", "21:9", 1584, 672),
    # gemini-3.x-image 2k
    ("gemini-3.x", "2k", "1:1", 2048, 2048),
    ("gemini-3.x", "2k", "1:4", 512, 2048),
    ("gemini-3.x", "2k", "1:8", 384, 3072),
    ("gemini-3.x", "2k", "2:3", 1696, 2528),
    ("gemini-3.x", "2k", "3:2", 2528, 1696),
    ("gemini-3.x", "2k", "3:4", 1792, 2400),
    ("gemini-3.x", "2k", "4:1", 2048, 512),
    ("gemini-3.x", "2k", "4:3", 2400, 1792),
    ("gemini-3.x", "2k", "4:5", 1856, 2304),
    ("gemini-3.x", "2k", "5:4", 2304, 1856),
    ("gemini-3.x", "2k", "8:1", 3072, 384),
    ("gemini-3.x", "2k", "9:16", 1536, 2752),
    ("gemini-3.x", "2k", "16:9", 2752, 1536),
    ("gemini-3.x", "2k", "21:9", 3168, 1344),
    # gemini-3.x-image 4k
    ("gemini-3.x", "4k", "1:1", 4096, 4096),
    ("gemini-3.x", "4k", "1:4", 2048, 8192),
    ("gemini-3.x", "4k", "1:8", 1536, 12288),
    ("gemini-3.x", "4k", "2:3", 3392, 5056),
    ("gemini-3.x", "4k", "3:2", 5056, 3392),
    ("gemini-3.x", "4k", "3:4", 3584, 4800),
    ("gemini-3.x", "4k", "4:1", 8192, 2048),
    ("gemini-3.x", "4k", "4:3", 4800, 3584),
    ("gemini-3.x", "4k", "4:5", 3712, 4608),
    ("gemini-3.x", "4k", "5:4", 4608, 3712),
    ("gemini-3.x", "4k", "8:1", 12288, 1536),
    ("gemini-3.x", "4k", "9:16", 3072, 5504),
    ("gemini-3.x", "4k", "16:9", 5504, 3072),
    ("gemini-3.x", "4k", "21:9", 6336, 2688),
    # gemini-2.5-flash-image 1k
    ("gemini-2.5-flash", "1k", "1:1", 1024, 1024),
    ("gemini-2.5-flash", "1k", "2:3", 832, 1248),
    ("gemini-2.5-flash", "1k", "3:2", 1248, 832),
    ("gemini-2.5-flash", "1k", "3:4", 864, 1184),
    ("gemini-2.5-flash", "1k", "4:3", 1184, 864),
    ("gemini-2.5-flash", "1k", "4:5", 896, 1152),
    ("gemini-2.5-flash", "1k", "5:4", 1152, 896),
    ("gemini-2.5-flash", "1k", "9:16", 768, 1344),
    ("gemini-2.5-flash", "1k", "16:9", 1344, 768),
    ("gemini-2.5-flash", "1k", "21:9", 1536, 672),
]

_SIZE_INDEX: dict[str, tuple[str, str]] = {}
for _model, _tier, _ratio, _w, _h in _OFFICIAL_GEMINI_SIZES:
    _SIZE_INDEX[f"{_w}x{_h}"] = (_model, _tier)


def _match_official_size(width: int, height: int) -> Optional[WatermarkConfig]:
    key = f"{width}x{height}"
    entry = _SIZE_INDEX.get(key)
    if entry is None:
        return None
    _model, tier = entry
    return WatermarkConfig(
        _WATERMARK_CONFIG_BY_TIER[tier].logo_size,
        _WATERMARK_CONFIG_BY_TIER[tier].margin_right,
        _WATERMARK_CONFIG_BY_TIER[tier].margin_bottom,
    )


def _resolve_official_search_configs(
    width: int,
    height: int,
    *,
    max_aspect_delta: float = 0.02,
    max_scale_mismatch: float = 0.12,
    limit: int = 3,
) -> list[WatermarkConfig]:
    exact = _match_official_size(width, height)
    if exact:
        return [exact]

    target_ar = width / height if height > 0 else 0
    candidates: list[tuple[float, WatermarkConfig]] = []

    for _model, tier, _ratio, ew, eh in _OFFICIAL_GEMINI_SIZES:
        base = _WATERMARK_CONFIG_BY_TIER.get(tier)
        if not base:
            continue
        scale_x = width / ew
        scale_y = height / eh
        scale = (scale_x + scale_y) / 2
        entry_ar = ew / eh if eh > 0 else 0
        rel_ar_delta = abs(target_ar - entry_ar) / max(entry_ar, 1e-6)
        sm = abs(scale_x - scale_y) / max(scale_x, scale_y, 1e-6)

        if rel_ar_delta > max_aspect_delta or sm > max_scale_mismatch:
            continue

        logo = _clamp(round(base.logo_size * scale), 24, 192)
        mr = max(8, round(base.margin_right * scale_x))
        mb = max(8, round(base.margin_bottom * scale_y))
        if width - mr - logo < 0 or height - mb - logo < 0:
            continue

        score = rel_ar_delta * 100 + sm * 20 + abs(math.log2(max(scale, 1e-6)))
        candidates.append((score, WatermarkConfig(logo, mr, mb)))

    candidates.sort(key=lambda c: c[0])
    seen: set[str] = set()
    result: list[WatermarkConfig] = []
    for _, cfg in candidates:
        key = f"{cfg.logo_size}:{cfg.margin_right}:{cfg.margin_bottom}"
        if key in seen:
            continue
        seen.add(key)
        result.append(cfg)
        if len(result) >= limit:
            break
    return result


# ---------------------------------------------------------------------------
# 基础工具函数
# ---------------------------------------------------------------------------
def _clamp(v: float, lo: float, hi: float) -> int:
    return int(max(lo, min(hi, v)))


def _to_grayscale(img: np.ndarray) -> np.ndarray:
    """将 (H,W,3) uint8 图片转为 (H*W,) float32 灰度"""
    return (
        0.2126 * img[:, :, 0].astype(np.float32)
        + 0.7152 * img[:, :, 1].astype(np.float32)
        + 0.0722 * img[:, :, 2].astype(np.float32)
    ) / 255.0


def _sobel_magnitude(gray: np.ndarray) -> np.ndarray:
    """对 2D 灰度图计算 Sobel 梯度幅值"""
    h, w = gray.shape
    grad = np.zeros_like(gray)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            gx = (
                -gray[y - 1, x - 1] - 2 * gray[y, x - 1] - gray[y + 1, x - 1]
                + gray[y - 1, x + 1] + 2 * gray[y, x + 1] + gray[y + 1, x + 1]
            )
            gy = (
                -gray[y - 1, x - 1] - 2 * gray[y - 1, x] - gray[y - 1, x + 1]
                + gray[y + 1, x - 1] + 2 * gray[y + 1, x] + gray[y + 1, x + 1]
            )
            grad[y, x] = math.sqrt(gx * gx + gy * gy)
    return grad


def _sobel_magnitude_fast(gray: np.ndarray) -> np.ndarray:
    """numpy 向量化 Sobel"""
    h, w = gray.shape
    if h < 3 or w < 3:
        return np.zeros_like(gray)
    # gx kernel
    gx = (
        -gray[:-2, :-2] - 2 * gray[1:-1, :-2] - gray[2:, :-2]
        + gray[:-2, 2:] + 2 * gray[1:-1, 2:] + gray[2:, 2:]
    )
    gy = (
        -gray[:-2, :-2] - 2 * gray[:-2, 1:-1] - gray[:-2, 2:]
        + gray[2:, :-2] + 2 * gray[2:, 1:-1] + gray[2:, 2:]
    )
    grad = np.zeros_like(gray)
    grad[1:-1, 1:-1] = np.sqrt(gx * gx + gy * gy)
    return grad


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关 (Normalized Cross-Correlation)"""
    if a.size != b.size or a.size == 0:
        return 0.0
    a_flat = a.ravel().astype(np.float64)
    b_flat = b.ravel().astype(np.float64)
    a_mean = a_flat.mean()
    b_mean = b_flat.mean()
    a_centered = a_flat - a_mean
    b_centered = b_flat - b_mean
    var_a = np.dot(a_centered, a_centered)
    var_b = np.dot(b_centered, b_centered)
    den = math.sqrt(var_a * var_b)
    if den < EPSILON:
        return 0.0
    return float(np.dot(a_centered, b_centered) / den)


def _extract_region_gray(img_gray: np.ndarray, x: int, y: int, size: int) -> np.ndarray:
    return img_gray[y:y + size, x:x + size].copy()


def _region_std(gray: np.ndarray, x: int, y: int, size: int) -> float:
    region = gray[y:y + size, x:x + size]
    if region.size == 0:
        return 0.0
    return float(region.std())


# ---------------------------------------------------------------------------
# Alpha Map 工具
# ---------------------------------------------------------------------------
def _interpolate_alpha_map(source: np.ndarray, source_size: int, target_size: int) -> np.ndarray:
    """双线性插值 alpha map 到目标尺寸"""
    if target_size <= 0:
        return np.zeros(0, dtype=np.float32)
    if source_size == target_size:
        return source.copy()

    out = np.zeros((target_size, target_size), dtype=np.float32)
    scale = (source_size - 1) / max(1, target_size - 1)

    for y in range(target_size):
        sy = y * scale
        y0 = int(sy)
        y1 = min(source_size - 1, y0 + 1)
        fy = sy - y0
        for x in range(target_size):
            sx = x * scale
            x0 = int(sx)
            x1 = min(source_size - 1, x0 + 1)
            fx = sx - x0
            p00 = source[y0, x0]
            p10 = source[y0, x1]
            p01 = source[y1, x0]
            p11 = source[y1, x1]
            top = p00 + (p10 - p00) * fx
            bottom = p01 + (p11 - p01) * fx
            out[y, x] = top + (bottom - top) * fy
    return out


def _warp_alpha_map(
    alpha_map: np.ndarray,
    size: int,
    dx: float = 0,
    dy: float = 0,
    scale: float = 1.0,
) -> np.ndarray:
    """对 alpha map 做亚像素级偏移和缩放"""
    if size <= 0:
        return np.zeros(0, dtype=np.float32)
    if dx == 0 and dy == 0 and scale == 1:
        return alpha_map.copy()

    c = (size - 1) / 2.0
    out = np.zeros((size, size), dtype=np.float32)
    for y in range(size):
        for x in range(size):
            sx = (x - c) / scale + c + dx
            sy = (y - c) / scale + c + dy
            x0 = _clamp(int(sx), 0, size - 1)
            y0 = _clamp(int(sy), 0, size - 1)
            x1 = _clamp(x0 + 1, 0, size - 1)
            y1 = _clamp(y0 + 1, 0, size - 1)
            fx = sx - int(sx)
            fy = sy - int(sy)
            fx = max(0.0, min(1.0, fx))
            fy = max(0.0, min(1.0, fy))
            p00 = alpha_map[y0, x0]
            p10 = alpha_map[y0, x1]
            p01 = alpha_map[y1, x0]
            p11 = alpha_map[y1, x1]
            top = p00 + (p10 - p00) * fx
            bottom = p01 + (p11 - p01) * fx
            out[y, x] = top + (bottom - top) * fy
    return out


# ---------------------------------------------------------------------------
# 核心混合算法 (blendModes)
# ---------------------------------------------------------------------------
def _remove_watermark_region(
    img_array: np.ndarray,
    alpha_map: np.ndarray,
    pos: WatermarkPosition,
    alpha_gain: float = 1.0,
) -> np.ndarray:
    """
    使用反向 Alpha 混合移除水印区域 (原地修改)

    新增: alpha 噪声底限 + alpha_gain 参数
    """
    x, y, w, h = pos.x, pos.y, pos.width, pos.height
    region = img_array[y:y + h, x:x + w].astype(np.float32)

    # 去噪: signal_alpha = max(0, raw - noise_floor) * gain
    signal_alpha = np.maximum(0, alpha_map - ALPHA_NOISE_FLOOR) * alpha_gain
    valid_mask = signal_alpha >= ALPHA_THRESHOLD

    # 用原始 alpha * gain 做反向求解
    alpha = np.minimum(alpha_map * alpha_gain, MAX_ALPHA)
    one_minus = 1.0 - alpha

    for c in range(3):
        channel = region[:, :, c]
        original = (channel - alpha * LOGO_VALUE) / one_minus
        channel[valid_mask] = original[valid_mask]

    region = np.clip(region, 0, 255)
    img_array[y:y + h, x:x + w] = region.astype(np.uint8)
    return img_array


# ---------------------------------------------------------------------------
# 恢复质量指标 (restorationMetrics)
# ---------------------------------------------------------------------------
def _calculate_near_black_ratio(img_array: np.ndarray, pos: WatermarkPosition) -> float:
    region = img_array[pos.y:pos.y + pos.height, pos.x:pos.x + pos.width]
    if region.size == 0:
        return 0.0
    mask = np.all(region <= NEAR_BLACK_THRESHOLD, axis=2)
    return float(mask.sum()) / (pos.width * pos.height)


def _region_texture_stats(img_array: np.ndarray, pos: WatermarkPosition) -> tuple[float, float]:
    """返回 (mean_lum, std_lum)"""
    region = img_array[pos.y:pos.y + pos.height, pos.x:pos.x + pos.width]
    lum = (
        0.2126 * region[:, :, 0].astype(np.float32)
        + 0.7152 * region[:, :, 1].astype(np.float32)
        + 0.0722 * region[:, :, 2].astype(np.float32)
    )
    return float(lum.mean()), float(lum.std())


def _assess_texture(
    original: np.ndarray,
    candidate: np.ndarray,
    pos: WatermarkPosition,
) -> tuple[bool, float]:
    """返回 (hard_reject, texture_penalty)"""
    ref_pos = WatermarkPosition(pos.x, pos.y - pos.height, pos.width, pos.height)
    if ref_pos.y < 0:
        return False, 0.0

    ref_mean, ref_std = _region_texture_stats(original, ref_pos)
    cand_mean, cand_std = _region_texture_stats(candidate, pos)

    dark_penalty = max(0, ref_mean - cand_mean - TEXTURE_REFERENCE_MARGIN) / max(1, ref_mean)
    flat_penalty = max(0, ref_std * TEXTURE_STD_FLOOR_RATIO - cand_std) / max(1, ref_std)
    too_dark = dark_penalty > 0
    too_flat = flat_penalty > 0
    hard_reject = too_dark and too_flat
    texture_penalty = dark_penalty * 2 + flat_penalty * 2
    return hard_reject, texture_penalty


def _compute_spatial_score(
    img_array: np.ndarray, alpha_map: np.ndarray, pos: WatermarkPosition,
) -> float:
    gray = _to_grayscale(img_array)
    patch = gray[pos.y:pos.y + pos.height, pos.x:pos.x + pos.width]
    if patch.shape[0] != alpha_map.shape[0] or patch.shape[1] != alpha_map.shape[1]:
        return 0.0
    return _ncc(patch, alpha_map)


def _compute_gradient_score(
    img_array: np.ndarray, alpha_map: np.ndarray, pos: WatermarkPosition,
) -> float:
    gray = _to_grayscale(img_array)
    patch = gray[pos.y:pos.y + pos.height, pos.x:pos.x + pos.width]
    if patch.shape[0] != alpha_map.shape[0] or patch.shape[1] != alpha_map.shape[1]:
        return 0.0
    patch_grad = _sobel_magnitude_fast(patch)
    alpha_grad = _sobel_magnitude_fast(alpha_map)
    return _ncc(patch_grad, alpha_grad)


def _score_region(
    img_array: np.ndarray, alpha_map: np.ndarray, pos: WatermarkPosition,
) -> RegionScores:
    return RegionScores(
        _compute_spatial_score(img_array, alpha_map, pos),
        _compute_gradient_score(img_array, alpha_map, pos),
    )


# ---------------------------------------------------------------------------
# 水印信号分类 (watermarkPresence / watermarkDecisionPolicy)
# ---------------------------------------------------------------------------
def _has_reliable_standard_signal(spatial: float, gradient: float) -> bool:
    return (
        (spatial >= STANDARD_DIRECT_MATCH_MIN_SPATIAL and gradient >= STANDARD_DIRECT_MATCH_MIN_GRADIENT)
        or (spatial >= STANDARD_STRONG_GRADIENT_MIN_SPATIAL and gradient >= STANDARD_STRONG_GRADIENT_MIN_GRADIENT)
    )


def _has_reliable_adaptive_signal(confidence: float, spatial: float, gradient: float, size: int) -> bool:
    return (
        confidence >= ADAPTIVE_DIRECT_MATCH_MIN_CONFIDENCE
        and spatial >= ADAPTIVE_DIRECT_MATCH_MIN_SPATIAL
        and gradient >= ADAPTIVE_DIRECT_MATCH_MIN_GRADIENT
        and 40 <= size <= 192
    )


# ---------------------------------------------------------------------------
# 检测配置
# ---------------------------------------------------------------------------
def _detect_watermark_config(width: int, height: int) -> WatermarkConfig:
    official = _match_official_size(width, height)
    if official:
        return official
    if width > 1024 and height > 1024:
        return WatermarkConfig(96, 64, 64)
    return WatermarkConfig(48, 32, 32)


def _calc_position(width: int, height: int, cfg: WatermarkConfig) -> WatermarkPosition:
    return WatermarkPosition(
        width - cfg.margin_right - cfg.logo_size,
        height - cfg.margin_bottom - cfg.logo_size,
        cfg.logo_size,
        cfg.logo_size,
    )


def _pos_inside(pos: WatermarkPosition, width: int, height: int) -> bool:
    return pos.x >= 0 and pos.y >= 0 and pos.x + pos.width <= width and pos.y + pos.height <= height


# ---------------------------------------------------------------------------
# 自适应检测 (adaptiveDetector)
# ---------------------------------------------------------------------------
@dataclass
class AdaptiveResult:
    found: bool
    confidence: float
    spatial_score: float
    gradient_score: float
    variance_score: float
    x: int
    y: int
    size: int


def _score_candidate(
    gray: np.ndarray,
    grad: np.ndarray,
    img_w: int,
    img_h: int,
    alpha_map: np.ndarray,
    template_grad: np.ndarray,
    x: int,
    y: int,
    size: int,
) -> Optional[tuple[float, float, float, float]]:
    """返回 (confidence, spatial, gradient, variance) 或 None"""
    if x < 0 or y < 0 or x + size > img_w or y + size > img_h:
        return None

    gray_region = gray[y:y + size, x:x + size]
    grad_region = grad[y:y + size, x:x + size]

    spatial = _ncc(gray_region, alpha_map)
    gradient = _ncc(grad_region, template_grad)

    variance_score = 0.0
    if y > 8:
        ref_y = max(0, y - size)
        ref_h = min(size, y - ref_y)
        if ref_h > 8:
            wm_std = float(gray[y:y + size, x:x + size].std())
            ref_std = float(gray[ref_y:ref_y + ref_h, x:x + size].std())
            if ref_std > EPSILON:
                variance_score = max(0.0, min(1.0, 1.0 - wm_std / ref_std))

    confidence = max(0, spatial) * 0.5 + max(0, gradient) * 0.3 + variance_score * 0.2
    confidence = max(0.0, min(1.0, confidence))
    return confidence, spatial, gradient, variance_score


def _detect_adaptive(
    img_array: np.ndarray,
    alpha96: np.ndarray,
    default_config: WatermarkConfig,
    get_alpha: callable,
    threshold: float = ADAPTIVE_DEFAULT_THRESHOLD,
) -> AdaptiveResult:
    """自适应多尺度多位置水印检测"""
    h, w = img_array.shape[:2]
    gray = _to_grayscale(img_array)
    grad = _sobel_magnitude_fast(gray)

    template_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def get_template(sz: int) -> tuple[np.ndarray, np.ndarray]:
        if sz in template_cache:
            return template_cache[sz]
        alpha = get_alpha(sz)
        tgrad = _sobel_magnitude_fast(alpha)
        template_cache[sz] = (alpha, tgrad)
        return alpha, tgrad

    # 构建搜索种子
    search_configs = _resolve_official_search_configs(w, h)
    if not any(
        c.logo_size == default_config.logo_size
        and c.margin_right == default_config.margin_right
        and c.margin_bottom == default_config.margin_bottom
        for c in search_configs
    ):
        search_configs.insert(0, default_config)

    seed_candidates: list[tuple[float, int, int, int, float, float, float]] = []
    for cfg in search_configs:
        sz = cfg.logo_size
        cx = w - cfg.margin_right - sz
        cy = h - cfg.margin_bottom - sz
        if cx < 0 or cy < 0 or cx + sz > w or cy + sz > h:
            continue
        alpha, tgrad = get_template(sz)
        result = _score_candidate(gray, grad, w, h, alpha, tgrad, cx, cy, sz)
        if result:
            conf, sp, gr, var = result
            seed_candidates.append((conf, cx, cy, sz, sp, gr, var))

    # 快速检查: 如果种子候选已经很好
    best_seed = max(seed_candidates, key=lambda c: c[0]) if seed_candidates else None
    if best_seed and best_seed[0] >= threshold + 0.08:
        return AdaptiveResult(
            True, best_seed[0], best_seed[4], best_seed[5], best_seed[6],
            best_seed[1], best_seed[2], best_seed[3],
        )

    # 粗搜索
    base_size = default_config.logo_size
    min_size = _clamp(round(base_size * 0.65), 24, 144)
    max_size = _clamp(
        min(round(base_size * 2.8), int(min(w, h) * 0.4)),
        min_size, 192,
    )
    scale_list = sorted(set(
        list(range(min_size, max_size + 1, 8)) + [48, 96]
    ))
    scale_list = [s for s in scale_list if min_size <= s <= max_size]

    margin_range = max(32, round(base_size * 0.75))
    min_mr = _clamp(default_config.margin_right - margin_range, 8, w - min_size - 1)
    max_mr = _clamp(default_config.margin_right + margin_range, min_mr, w - min_size - 1)
    min_mb = _clamp(default_config.margin_bottom - margin_range, 8, h - min_size - 1)
    max_mb = _clamp(default_config.margin_bottom + margin_range, min_mb, h - min_size - 1)

    top_k: list[tuple[float, int, int, int]] = []
    for sc in seed_candidates:
        adj = sc[0] * min(1.0, math.sqrt(sc[3] / 96))
        top_k.append((adj, sc[1], sc[2], sc[3]))

    def push_top_k(adj: float, x: int, y: int, sz: int):
        top_k.append((adj, x, y, sz))
        top_k.sort(key=lambda c: -c[0])
        while len(top_k) > 5:
            top_k.pop()

    for sz in scale_list:
        alpha, tgrad = get_template(sz)
        for mr in range(min_mr, max_mr + 1, 8):
            cx = w - mr - sz
            if cx < 0:
                continue
            for mb in range(min_mb, max_mb + 1, 8):
                cy = h - mb - sz
                if cy < 0:
                    continue
                result = _score_candidate(gray, grad, w, h, alpha, tgrad, cx, cy, sz)
                if not result:
                    continue
                conf = result[0]
                adj = conf * min(1.0, math.sqrt(sz / 96))
                if adj < 0.08:
                    continue
                push_top_k(adj, cx, cy, sz)

    # 初始化 best
    if best_seed:
        best = list(best_seed)
    else:
        fx = w - default_config.margin_right - default_config.logo_size
        fy = h - default_config.margin_bottom - default_config.logo_size
        best = [0.0, fx, fy, default_config.logo_size, 0.0, 0.0, 0.0]

    # 精细搜索
    for _, cx, cy, sz in top_k:
        scale_lo = _clamp(sz - 10, min_size, max_size)
        scale_hi = _clamp(sz + 10, min_size, max_size)
        for s in range(scale_lo, scale_hi + 1, 2):
            alpha, tgrad = get_template(s)
            for x in range(cx - 8, cx + 9, 2):
                if x < 0 or x + s > w:
                    continue
                for y in range(cy - 8, cy + 9, 2):
                    if y < 0 or y + s > h:
                        continue
                    result = _score_candidate(gray, grad, w, h, alpha, tgrad, x, y, s)
                    if result and result[0] > best[0]:
                        best = [result[0], x, y, s, result[1], result[2], result[3]]

    return AdaptiveResult(
        found=best[0] >= threshold,
        confidence=best[0],
        spatial_score=best[4],
        gradient_score=best[5],
        variance_score=best[6],
        x=best[1],
        y=best[2],
        size=best[3],
    )


# ---------------------------------------------------------------------------
# 候选评估与选择
# ---------------------------------------------------------------------------
@dataclass
class CandidateResult:
    accepted: bool
    source: str
    config: WatermarkConfig
    position: WatermarkPosition
    alpha_map: np.ndarray
    alpha_gain: float
    original_spatial: float
    original_gradient: float
    processed_spatial: float
    processed_gradient: float
    improvement: float
    near_black_ratio: float
    near_black_increase: float
    hard_reject: bool
    texture_penalty: float
    validation_cost: float
    img_array: Optional[np.ndarray] = None


def _evaluate_candidate(
    original: np.ndarray,
    alpha_map: np.ndarray,
    pos: WatermarkPosition,
    source: str,
    config: WatermarkConfig,
    alpha_gain: float = 1.0,
    include_image: bool = True,
) -> Optional[CandidateResult]:
    if alpha_map is None or pos is None:
        return None

    orig_scores = _score_region(original, alpha_map, pos)
    baseline_nbr = _calculate_near_black_ratio(original, pos)

    candidate = original.copy()
    _remove_watermark_region(candidate, alpha_map, pos, alpha_gain)

    proc_scores = _score_region(candidate, alpha_map, pos)
    nbr = _calculate_near_black_ratio(candidate, pos)
    nbr_increase = nbr - baseline_nbr
    improvement = orig_scores.spatial_score - proc_scores.spatial_score
    grad_increase = proc_scores.gradient_score - orig_scores.gradient_score

    hard_reject, tex_penalty = _assess_texture(original, candidate, pos)

    accepted = (
        not hard_reject
        and nbr_increase <= MAX_NEAR_BLACK_RATIO_INCREASE
        and improvement >= VALIDATION_MIN_IMPROVEMENT
        and (
            abs(proc_scores.spatial_score) <= VALIDATION_TARGET_RESIDUAL
            or grad_increase <= VALIDATION_MAX_GRADIENT_INCREASE
        )
    )

    cost = (
        abs(proc_scores.spatial_score)
        + max(0, proc_scores.gradient_score) * 0.6
        + max(0, nbr_increase) * 3
        + tex_penalty
    )

    return CandidateResult(
        accepted=accepted,
        source=source,
        config=config,
        position=pos,
        alpha_map=alpha_map,
        alpha_gain=alpha_gain,
        original_spatial=orig_scores.spatial_score,
        original_gradient=orig_scores.gradient_score,
        processed_spatial=proc_scores.spatial_score,
        processed_gradient=proc_scores.gradient_score,
        improvement=improvement,
        near_black_ratio=nbr,
        near_black_increase=nbr_increase,
        hard_reject=hard_reject,
        texture_penalty=tex_penalty,
        validation_cost=cost,
        img_array=candidate if include_image else None,
    )


def _pick_better(current: Optional[CandidateResult], candidate: Optional[CandidateResult]) -> Optional[CandidateResult]:
    if not candidate or not candidate.accepted:
        return current
    if not current:
        return candidate
    if candidate.validation_cost < current.validation_cost - 0.005:
        return candidate
    if (
        abs(candidate.validation_cost - current.validation_cost) <= 0.005
        and candidate.improvement > current.improvement + 0.01
    ):
        return candidate
    return current


# ---------------------------------------------------------------------------
# 多次移除 (multiPassRemoval)
# ---------------------------------------------------------------------------
def _remove_repeated_layers(
    img_array: np.ndarray,
    alpha_map: np.ndarray,
    pos: WatermarkPosition,
    max_passes: int = DEFAULT_MAX_PASSES,
    starting_pass: int = 0,
    alpha_gain: float = 1.0,
) -> tuple[np.ndarray, int, str]:
    """返回 (result_array, pass_count, stop_reason)"""
    current = img_array.copy()
    base_nbr = _calculate_near_black_ratio(current, pos)
    max_nbr = min(1.0, base_nbr + MAX_NEAR_BLACK_RATIO_INCREASE)
    applied = starting_pass
    stop_reason = "max-passes"

    for _ in range(max_passes):
        before = _score_region(current, alpha_map, pos)
        candidate = current.copy()
        _remove_watermark_region(candidate, alpha_map, pos, alpha_gain)
        after = _score_region(candidate, alpha_map, pos)
        nbr = _calculate_near_black_ratio(candidate, pos)

        if nbr > max_nbr:
            stop_reason = "safety-near-black"
            break

        # 纹理坍缩检查
        hard_reject, _ = _assess_texture(current, candidate, pos)
        if hard_reject:
            stop_reason = "safety-texture-collapse"
            break

        current = candidate
        applied += 1

        if abs(after.spatial_score) <= DEFAULT_RESIDUAL_THRESHOLD:
            stop_reason = "residual-low"
            break

    return current, applied, stop_reason


# ---------------------------------------------------------------------------
# Alpha Gain 校准
# ---------------------------------------------------------------------------
def _recalibrate_alpha_gain(
    source: np.ndarray,
    alpha_map: np.ndarray,
    pos: WatermarkPosition,
    original_spatial: float,
    processed_spatial: float,
) -> Optional[tuple[np.ndarray, float, float]]:
    """尝试不同 alpha gain 找到最优移除效果。返回 (img, gain, score) 或 None"""
    original_nbr = _calculate_near_black_ratio(source, pos)
    max_nbr = min(1.0, original_nbr + MAX_NEAR_BLACK_RATIO_INCREASE)

    best_score = processed_spatial
    best_gain = 1.0
    best_img = None

    # 粗搜索
    for gain in ALPHA_GAIN_CANDIDATES:
        candidate = source.copy()
        _remove_watermark_region(candidate, alpha_map, pos, gain)
        nbr = _calculate_near_black_ratio(candidate, pos)
        if nbr > max_nbr:
            continue
        score = _compute_spatial_score(candidate, alpha_map, pos)
        if score < best_score:
            best_score = score
            best_gain = gain
            best_img = candidate

    # 精细搜索
    for delta in np.arange(-0.05, 0.06, 0.01):
        gain = round(best_gain + delta, 2)
        if gain <= 1.0 or gain >= 3.0:
            continue
        candidate = source.copy()
        _remove_watermark_region(candidate, alpha_map, pos, gain)
        nbr = _calculate_near_black_ratio(candidate, pos)
        if nbr > max_nbr:
            continue
        score = _compute_spatial_score(candidate, alpha_map, pos)
        if score < best_score:
            best_score = score
            best_gain = gain
            best_img = candidate

    delta = processed_spatial - best_score
    if best_img is None or delta < MIN_RECALIBRATION_SCORE_DELTA:
        return None
    return best_img, best_gain, best_score


# ---------------------------------------------------------------------------
# 亚像素精细化
# ---------------------------------------------------------------------------
def _refine_subpixel(
    source: np.ndarray,
    alpha_map: np.ndarray,
    pos: WatermarkPosition,
    alpha_gain: float,
    baseline_spatial: float,
    baseline_gradient: float,
    baseline_shift: Optional[dict] = None,
) -> Optional[tuple[np.ndarray, np.ndarray, float, dict]]:
    """返回 (img, warped_alpha, gain, shift_dict) 或 None"""
    size = pos.width
    if size <= 8 or alpha_gain < OUTLINE_REFINEMENT_MIN_GAIN:
        return None

    orig_nbr = _calculate_near_black_ratio(source, pos)
    max_nbr = min(1.0, orig_nbr + MAX_NEAR_BLACK_RATIO_INCREASE)

    base_dx = (baseline_shift or {}).get("dx", 0.0)
    base_dy = (baseline_shift or {}).get("dy", 0.0)
    base_scale = (baseline_shift or {}).get("scale", 1.0)

    gain_candidates = [alpha_gain]
    lower = max(1.0, round(alpha_gain - 0.01, 2))
    upper = round(alpha_gain + 0.01, 2)
    if lower != alpha_gain:
        gain_candidates.append(lower)
    if upper != alpha_gain:
        gain_candidates.append(upper)

    best = None
    best_cost = float("inf")

    for sd in SUBPIXEL_REFINE_SCALES:
        s = round(base_scale * sd, 4)
        for dyd in SUBPIXEL_REFINE_SHIFTS:
            dy_val = base_dy + dyd
            for dxd in SUBPIXEL_REFINE_SHIFTS:
                dx_val = base_dx + dxd
                warped = _warp_alpha_map(alpha_map, size, dx_val, dy_val, s)
                for g in gain_candidates:
                    candidate = source.copy()
                    _remove_watermark_region(candidate, warped, pos, g)
                    nbr = _calculate_near_black_ratio(candidate, pos)
                    if nbr > max_nbr:
                        continue
                    sp = _compute_spatial_score(candidate, warped, pos)
                    gr = _compute_gradient_score(candidate, warped, pos)
                    cost = abs(sp) * 0.6 + max(0, gr)
                    if cost < best_cost:
                        best_cost = cost
                        best = (candidate, warped, g, {"dx": dx_val, "dy": dy_val, "scale": s}, sp, gr)

    if best is None:
        return None

    img, warped, gain, shift, sp, gr = best
    improved_gradient = gr <= baseline_gradient - 0.04
    kept_spatial = abs(sp) <= abs(baseline_spatial) + 0.08
    if not improved_gradient or not kept_spatial:
        return None
    return img, warped, gain, shift


# ---------------------------------------------------------------------------
# 模板变形搜索
# ---------------------------------------------------------------------------
TEMPLATE_ALIGN_SHIFTS = [-0.5, -0.25, 0.0, 0.25, 0.5]
TEMPLATE_ALIGN_SCALES = [0.99, 1.0, 1.01]


def _find_best_template_warp(
    img_array: np.ndarray,
    alpha_map: np.ndarray,
    pos: WatermarkPosition,
    baseline_spatial: float,
    baseline_gradient: float,
) -> Optional[tuple[np.ndarray, dict]]:
    """返回 (warped_alpha, shift_dict) 或 None"""
    size = pos.width
    if size <= 8:
        return None

    best_spatial = baseline_spatial
    best_gradient = baseline_gradient
    best_warp = None
    best_shift = None

    for s in TEMPLATE_ALIGN_SCALES:
        for dy in TEMPLATE_ALIGN_SHIFTS:
            for dx in TEMPLATE_ALIGN_SHIFTS:
                if dx == 0 and dy == 0 and s == 1:
                    continue
                warped = _warp_alpha_map(alpha_map, size, dx, dy, s)
                sp = _compute_spatial_score(img_array, warped, pos)
                gr = _compute_gradient_score(img_array, warped, pos)

                conf = max(0, sp) * 0.7 + max(0, gr) * 0.3
                best_conf = max(0, best_spatial) * 0.7 + max(0, best_gradient) * 0.3
                if conf > best_conf + 0.01:
                    best_spatial = sp
                    best_gradient = gr
                    best_warp = warped
                    best_shift = {"dx": dx, "dy": dy, "scale": s}

    if best_warp is None:
        return None
    improved_sp = best_spatial >= baseline_spatial + 0.01
    improved_gr = best_gradient >= baseline_gradient + 0.01
    if not (improved_sp or improved_gr):
        return None
    return best_warp, best_shift


# ---------------------------------------------------------------------------
# 主处理器
# ---------------------------------------------------------------------------
class GeminiWatermarkRemover:
    """
    Gemini 图片去水印器 v2

    使用方式:
        remover = GeminiWatermarkRemover()
        remover.remove_watermark(image_path)  # 原地修改
    """

    def __init__(self):
        self._alpha_maps: dict[int, np.ndarray] = {}
        self._load_alpha_maps()

    def _load_alpha_maps(self):
        for size, path in [(48, BG_48_PATH), (96, BG_96_PATH)]:
            if not path.exists():
                logger.warning("Alpha map 文件不存在: %s", path)
                continue
            bg_img = Image.open(path).convert("RGB")
            bg_array = np.array(bg_img, dtype=np.float32)
            self._alpha_maps[size] = np.max(bg_array, axis=2) / 255.0
            logger.debug("已加载 %dx%d alpha map", size, size)

    def _get_alpha(self, size: int) -> np.ndarray:
        if size in self._alpha_maps:
            return self._alpha_maps[size]
        if 96 in self._alpha_maps:
            interp = _interpolate_alpha_map(self._alpha_maps[96], 96, size)
            self._alpha_maps[size] = interp
            return interp
        if 48 in self._alpha_maps:
            interp = _interpolate_alpha_map(self._alpha_maps[48], 48, size)
            self._alpha_maps[size] = interp
            return interp
        raise RuntimeError(f"No base alpha map available for interpolation to {size}")

    def _process(self, img_array: np.ndarray) -> np.ndarray:
        """核心处理流程"""
        h, w = img_array.shape[:2]
        alpha48 = self._get_alpha(48)
        alpha96 = self._get_alpha(96)

        # 1. 检测默认配置
        default_config = _detect_watermark_config(w, h)

        # 2. 解析初始标准配置 (对比 48/96 模板相关性选择更好的)
        config = self._resolve_initial_config(img_array, default_config, alpha48, alpha96)
        pos = _calc_position(w, h, config)
        alpha_map = self._get_alpha(config.logo_size)

        # 3. 候选选择
        selected = self._select_initial_candidate(
            img_array, config, pos, alpha48, alpha96,
        )

        if selected is None:
            logger.debug("未检测到水印信号，跳过处理")
            return img_array

        result_img = selected.img_array if selected.img_array is not None else img_array.copy()
        pos = selected.position
        alpha_map = selected.alpha_map
        config = selected.config
        alpha_gain = selected.alpha_gain
        source = selected.source

        # 4. 首次 pass 度量
        first_sp = _compute_spatial_score(result_img, alpha_map, pos)
        first_gr = _compute_gradient_score(result_img, alpha_map, pos)
        orig_sp = selected.original_spatial
        orig_gr = selected.original_gradient

        # 5. 判断是否需要多次移除
        first_pass_cleared = self._should_stop_after_first(
            orig_sp, orig_gr, first_sp, first_gr,
        )

        pass_count = 1
        if not first_pass_cleared:
            result_img, pass_count, stop_reason = _remove_repeated_layers(
                result_img, alpha_map, pos,
                max_passes=DEFAULT_MAX_PASSES - 1,
                starting_pass=1,
                alpha_gain=alpha_gain,
            )
            if pass_count > 1:
                source = f"{source}+multipass"

        # 6. 最终度量
        proc_sp = _compute_spatial_score(result_img, alpha_map, pos)
        proc_gr = _compute_gradient_score(result_img, alpha_map, pos)
        suppression = orig_sp - proc_sp

        # 7. Alpha gain 校准
        if self._should_recalibrate(orig_sp, proc_sp, suppression):
            recal = _recalibrate_alpha_gain(
                result_img, alpha_map, pos, orig_sp, proc_sp,
            )
            if recal:
                result_img, alpha_gain, proc_sp = recal
                proc_gr = _compute_gradient_score(result_img, alpha_map, pos)
                suppression = orig_sp - proc_sp
                source = f"{source}+gain"

        # 8. 亚像素精细化
        if proc_sp <= 0.3 and proc_gr >= OUTLINE_REFINEMENT_THRESHOLD:
            refined = _refine_subpixel(
                result_img, alpha_map, pos, alpha_gain,
                proc_sp, proc_gr,
            )
            if refined:
                result_img, alpha_map, alpha_gain, shift = refined
                proc_sp = _compute_spatial_score(result_img, alpha_map, pos)
                proc_gr = _compute_gradient_score(result_img, alpha_map, pos)
                source = f"{source}+subpixel"

        logger.info(
            "去水印完成: %dx%d logo=%d source=%s gain=%.2f passes=%d "
            "spatial=%.3f→%.3f gradient=%.3f→%.3f",
            w, h, config.logo_size, source, alpha_gain, pass_count,
            orig_sp, proc_sp, orig_gr, proc_gr,
        )
        return result_img

    def _resolve_initial_config(
        self,
        img_array: np.ndarray,
        default_config: WatermarkConfig,
        alpha48: np.ndarray,
        alpha96: np.ndarray,
    ) -> WatermarkConfig:
        """比较 48/96 和目录配置，选择相关性最好的"""
        h, w = img_array.shape[:2]
        candidates: list[WatermarkConfig] = []

        # 标准 48/96
        if default_config.logo_size == 96:
            candidates.append(WatermarkConfig(96, 64, 64))
            candidates.append(WatermarkConfig(48, 32, 32))
        else:
            candidates.append(WatermarkConfig(48, 32, 32))
            candidates.append(WatermarkConfig(96, 64, 64))

        # 目录推荐
        for cfg in _resolve_official_search_configs(w, h, limit=1):
            if not any(
                c.logo_size == cfg.logo_size
                and c.margin_right == cfg.margin_right
                and c.margin_bottom == cfg.margin_bottom
                for c in candidates
            ):
                candidates.append(cfg)

        best_config = default_config
        best_score = float("-inf")
        min_switch = 0.25
        min_delta = 0.08

        for cfg in candidates:
            pos = _calc_position(w, h, cfg)
            if not _pos_inside(pos, w, h):
                continue
            alpha = self._get_alpha(cfg.logo_size)
            score = _compute_spatial_score(img_array, alpha, pos)

            if best_config is None:
                best_config = cfg
                best_score = score
            elif score >= min_switch and score > best_score + min_delta:
                best_config = cfg
                best_score = score

        return best_config

    def _select_initial_candidate(
        self,
        img_array: np.ndarray,
        config: WatermarkConfig,
        pos: WatermarkPosition,
        alpha48: np.ndarray,
        alpha96: np.ndarray,
    ) -> Optional[CandidateResult]:
        """综合候选选择"""
        h, w = img_array.shape[:2]
        alpha_map = self._get_alpha(config.logo_size)

        # 标准候选
        std_trial = _evaluate_candidate(
            img_array, alpha_map, pos, "standard", config,
        )

        std_sp = std_trial.original_spatial if std_trial else 0
        std_gr = std_trial.original_gradient if std_trial else 0
        reliable_std = _has_reliable_standard_signal(std_sp, std_gr)

        best: Optional[CandidateResult] = None
        if reliable_std:
            best = std_trial
        elif std_trial and std_trial.accepted:
            best = std_trial

        # 如果标准候选不够好，尝试目录变体
        if not reliable_std or self._should_escalate(best):
            for cfg in _resolve_official_search_configs(w, h):
                if (
                    cfg.logo_size == config.logo_size
                    and cfg.margin_right == config.margin_right
                    and cfg.margin_bottom == config.margin_bottom
                ):
                    continue
                cpos = _calc_position(w, h, cfg)
                if not _pos_inside(cpos, w, h):
                    continue
                calpha = self._get_alpha(cfg.logo_size)
                trial = _evaluate_candidate(
                    img_array, calpha, cpos, "standard+catalog", cfg,
                )
                best = _pick_better(best, trial)

        # 尺寸抖动搜索
        if not reliable_std and self._should_escalate(best):
            for delta in [-12, -10, -8, -6, -4, -2, 2, 4, 6, 8, 10, 12]:
                sz = config.logo_size + delta
                if sz <= 24:
                    continue
                jpos = WatermarkPosition(
                    w - config.margin_right - sz,
                    h - config.margin_bottom - sz,
                    sz, sz,
                )
                if not _pos_inside(jpos, w, h):
                    continue
                jalpha = self._get_alpha(sz)
                jcfg = WatermarkConfig(sz, config.margin_right, config.margin_bottom)
                trial = _evaluate_candidate(
                    img_array, jalpha, jpos, "standard+size", jcfg,
                    include_image=False,
                )
                best = _pick_better(best, trial)

        # Alpha gain 搜索
        if best and self._should_escalate(best):
            for gain in ALPHA_GAIN_CANDIDATES:
                trial = _evaluate_candidate(
                    img_array, best.alpha_map, best.position,
                    f"{best.source}+gain", best.config,
                    alpha_gain=gain,
                    include_image=False,
                )
                best = _pick_better(best, trial)

        # 自适应搜索
        if self._should_escalate(best):
            adaptive = _detect_adaptive(
                img_array, alpha96, config, self._get_alpha,
            )
            if adaptive.found and adaptive.confidence >= 0.25:
                apos = WatermarkPosition(
                    adaptive.x, adaptive.y, adaptive.size, adaptive.size,
                )
                aalpha = self._get_alpha(adaptive.size)
                acfg = WatermarkConfig(
                    adaptive.size,
                    w - adaptive.x - adaptive.size,
                    h - adaptive.y - adaptive.size,
                )
                trial = _evaluate_candidate(
                    img_array, aalpha, apos, "adaptive", acfg,
                )
                best = _pick_better(best, trial)

                # 自适应 + gain
                if trial and self._should_escalate(best):
                    for gain in ALPHA_GAIN_CANDIDATES:
                        gtrial = _evaluate_candidate(
                            img_array, aalpha, apos,
                            "adaptive+gain", acfg,
                            alpha_gain=gain,
                            include_image=False,
                        )
                        best = _pick_better(best, gtrial)

        if best is None:
            return None

        # 模板变形
        warp_result = _find_best_template_warp(
            img_array, best.alpha_map, best.position,
            best.original_spatial, best.original_gradient,
        )
        if warp_result:
            warped_alpha, shift = warp_result
            wtrial = _evaluate_candidate(
                img_array, warped_alpha, best.position,
                f"{best.source}+warp", best.config,
            )
            better = _pick_better(best, wtrial)
            if better is not None and better is not best:
                best = better

        # 确保有图片数据
        if best.img_array is None:
            candidate = img_array.copy()
            _remove_watermark_region(candidate, best.alpha_map, best.position, best.alpha_gain)
            best = CandidateResult(
                accepted=best.accepted,
                source=best.source,
                config=best.config,
                position=best.position,
                alpha_map=best.alpha_map,
                alpha_gain=best.alpha_gain,
                original_spatial=best.original_spatial,
                original_gradient=best.original_gradient,
                processed_spatial=best.processed_spatial,
                processed_gradient=best.processed_gradient,
                improvement=best.improvement,
                near_black_ratio=best.near_black_ratio,
                near_black_increase=best.near_black_increase,
                hard_reject=best.hard_reject,
                texture_penalty=best.texture_penalty,
                validation_cost=best.validation_cost,
                img_array=candidate,
            )

        return best

    @staticmethod
    def _should_escalate(candidate: Optional[CandidateResult]) -> bool:
        if candidate is None:
            return True
        return (
            abs(candidate.processed_spatial) > STANDARD_FAST_PATH_RESIDUAL_THRESHOLD
            or max(0, candidate.processed_gradient) > STANDARD_FAST_PATH_GRADIENT_THRESHOLD
        )

    @staticmethod
    def _should_recalibrate(orig_sp: float, proc_sp: float, suppression: float) -> bool:
        return (
            orig_sp >= 0.6
            and proc_sp >= RESIDUAL_RECALIBRATION_THRESHOLD
            and suppression <= MIN_SUPPRESSION_FOR_SKIP_RECALIBRATION
        )

    @staticmethod
    def _should_stop_after_first(
        orig_sp: float, orig_gr: float, first_sp: float, first_gr: float,
    ) -> bool:
        if abs(first_sp) <= 0.25:
            return True
        return (
            orig_sp >= 0
            and first_sp < 0
            and first_gr <= FIRST_PASS_SIGN_FLIP_GRADIENT_THRESHOLD
            and (orig_gr - first_gr) >= FIRST_PASS_SIGN_FLIP_MIN_GRADIENT_DROP
        )

    def remove_watermark(
        self,
        image_path: Path,
        output_path: Optional[Path] = None,
    ) -> Path:
        image_path = Path(image_path)
        if output_path is None:
            output_path = image_path

        img = Image.open(image_path)
        width, height = img.size

        # 保持原始模式
        alpha_channel = None
        if img.mode == "RGBA":
            alpha_channel = img.split()[3]
            img_rgb = img.convert("RGB")
        elif img.mode != "RGB":
            img_rgb = img.convert("RGB")
        else:
            img_rgb = img

        img_array = np.array(img_rgb)
        result_array = self._process(img_array)

        result_img = Image.fromarray(result_array, mode="RGB")
        if alpha_channel is not None:
            result_img = result_img.convert("RGBA")
            result_img.putalpha(alpha_channel)

        result_img.save(output_path)
        return output_path

    async def remove_watermark_async(
        self,
        image_path: Path,
        output_path: Optional[Path] = None,
    ) -> Path:
        return await asyncio.to_thread(self.remove_watermark, image_path, output_path)


# ---------------------------------------------------------------------------
# 公共 API（保持向后兼容）
# ---------------------------------------------------------------------------
_remover: Optional[GeminiWatermarkRemover] = None


def get_watermark_remover() -> GeminiWatermarkRemover:
    global _remover
    if _remover is None:
        _remover = GeminiWatermarkRemover()
    return _remover


def remove_gemini_watermark(
    image_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    remover = get_watermark_remover()
    return remover.remove_watermark(image_path, output_path)


async def remove_gemini_watermark_async(
    image_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    remover = get_watermark_remover()
    return await remover.remove_watermark_async(image_path, output_path)
