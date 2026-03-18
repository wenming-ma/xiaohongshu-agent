"""
图片后处理管线 - 降低 AI 检测标记

6阶段处理:
1. 元数据清洗 - 去除 C2PA/EXIF/XMP/IPTC
2. 相机噪声模拟 - 对抗像素统计检测
3. 微几何变换 - 对抗频域指纹检测
4. JPEG 重编码 - 破坏残余特征
4b. 仿真 EXIF 注入 - 伪装为真实手机拍摄
5. 输出验证 - 确认 AI 标记已清除
"""
import asyncio
import io
import random
import struct
from datetime import datetime, timedelta
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

        # Stage 4b: 仿真 EXIF 注入
        self._inject_camera_exif(output_path, original_size)

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

    # 常见手机相机配置 (Make, Model, Software, FocalLength_mm, FNumber, ISORange)
    _CAMERA_PROFILES = [
        ("Apple", "iPhone 15 Pro", "17.4.1", 6.86, 1.78, (50, 200)),
        ("Apple", "iPhone 14", "17.3.1", 5.7, 1.6, (50, 320)),
        ("Apple", "iPhone 16 Pro Max", "18.3.2", 6.86, 1.78, (50, 160)),
        ("Xiaomi", "2211133C", "14.0.11", 6.81, 1.88, (50, 400)),
        ("Xiaomi", "23127PN0CC", "15.0.4", 5.59, 1.79, (64, 320)),
        ("HUAWEI", "NOH-AN00", "12.0.0", 5.58, 1.8, (50, 400)),
        ("HUAWEI", "ALT-AL00", "14.1.0", 6.52, 1.85, (50, 320)),
        ("samsung", "SM-S9280", "UP1A.231005.007", 6.3, 1.7, (50, 250)),
        ("OPPO", "PGJM10", "14.0.0", 5.59, 1.79, (100, 400)),
        ("vivo", "V2329A", "14.0.0", 5.56, 1.88, (50, 320)),
    ]

    def _inject_camera_exif(self, file_path: Path, image_size: tuple[int, int]) -> None:
        """Stage 4b: 注入仿真相机 EXIF，伪装为真实手机拍摄"""
        make, model, software, focal, fnum, iso_range = random.choice(self._CAMERA_PROFILES)
        w, h = image_size
        iso = random.randint(*iso_range)
        # 随机生成近 7 天内的拍摄时间
        now = datetime.now()
        shot_time = now - timedelta(
            days=random.randint(0, 6),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )
        dt_str = shot_time.strftime("%Y:%m:%d %H:%M:%S")
        # 快门速度 1/60 ~ 1/2000
        exposure_num = random.choice([60, 100, 125, 200, 250, 500, 800, 1000, 1600, 2000])

        exif = self._build_exif_bytes(
            make=make, model=model, software=software,
            dt_str=dt_str, focal_mm=focal, fnum=fnum,
            iso=iso, exposure_denom=exposure_num,
            width=w, height=h,
        )
        self._patch_jpeg_exif(file_path, exif)
        logger.debug("Stage 4b: EXIF 已注入 (%s %s, ISO %d, %s)", make, model, iso, dt_str)

    @staticmethod
    def _build_exif_bytes(
        *, make: str, model: str, software: str,
        dt_str: str, focal_mm: float, fnum: float,
        iso: int, exposure_denom: int,
        width: int, height: int,
    ) -> bytes:
        """构建最小化但完整的 EXIF APP1 段（纯手工拼接，不依赖第三方 EXIF 库）"""
        # TIFF header: little-endian
        BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5

        def _encode_str(s: str) -> bytes:
            b = s.encode("ascii") + b"\x00"
            # pad to even length
            if len(b) % 2:
                b += b"\x00"
            return b

        def _rational(num: int, den: int) -> bytes:
            return struct.pack("<II", num, den)

        # IFD0 tags we want:
        # 0x010F Make, 0x0110 Model, 0x0112 Orientation, 0x011A XRes, 0x011B YRes,
        # 0x0128 ResUnit, 0x0131 Software, 0x0132 DateTime, 0x8769 ExifIFD pointer
        # ExifIFD tags:
        # 0x829A ExposureTime, 0x829D FNumber, 0x8827 ISO, 0x9000 ExifVersion,
        # 0x9003 DateTimeOriginal, 0x9004 DateTimeDigitized,
        # 0xA002 PixelXDimension, 0xA003 PixelYDimension, 0x920A FocalLength

        ifd0_tags = []
        exif_tags = []
        data_blobs = []  # (offset_placeholder_index, data_bytes)

        # We'll build the IFD entry list, then compute offsets after
        # Structure: TIFF header (8) + IFD0 entries + next_ifd(4) + IFD0 data + ExifIFD entries + next_ifd(4) + ExifIFD data

        make_b = _encode_str(make)
        model_b = _encode_str(model)
        software_b = _encode_str(software)
        dt_b = _encode_str(dt_str)  # 20 bytes "YYYY:MM:DD HH:MM:SS\0"

        xres = _rational(72, 1)
        yres = _rational(72, 1)
        exposure = _rational(1, exposure_denom)
        fnum_r = _rational(int(fnum * 100), 100)
        focal_r = _rational(int(focal_mm * 100), 100)

        # Build everything into a byte buffer
        buf = io.BytesIO()

        # TIFF header
        buf.write(b"II")           # little-endian
        buf.write(struct.pack("<H", 42))  # magic
        buf.write(struct.pack("<I", 8))   # offset to IFD0

        # --- IFD0 ---
        ifd0_count = 9
        ifd0_start = 8
        ifd0_entries_size = 2 + ifd0_count * 12 + 4  # count(2) + entries + next_ifd(4)
        ifd0_data_offset = ifd0_start + ifd0_entries_size

        # Collect IFD0 data area items: (tag, type, count, value_or_data)
        ifd0_data_area = io.BytesIO()

        def _ifd0_entry(tag: int, typ: int, count: int, value: bytes) -> bytes:
            """Create an IFD entry; if value > 4 bytes, store in data area."""
            if len(value) <= 4:
                return struct.pack("<HHIH", tag, typ, count, 0)[:-2] + value.ljust(4, b"\x00")
            offset = ifd0_data_offset + ifd0_data_area.tell()
            ifd0_data_area.write(value)
            entry = struct.pack("<HHI", tag, typ, count) + struct.pack("<I", offset)
            return entry

        buf.write(struct.pack("<H", ifd0_count))

        buf.write(_ifd0_entry(0x010F, ASCII, len(make_b), make_b))
        buf.write(_ifd0_entry(0x0110, ASCII, len(model_b), model_b))
        buf.write(_ifd0_entry(0x0112, SHORT, 1, struct.pack("<H", 1)))  # Orientation=1
        buf.write(_ifd0_entry(0x011A, RATIONAL, 1, xres))
        buf.write(_ifd0_entry(0x011B, RATIONAL, 1, yres))
        buf.write(_ifd0_entry(0x0128, SHORT, 1, struct.pack("<H", 2)))  # ResUnit=inch
        buf.write(_ifd0_entry(0x0131, ASCII, len(software_b), software_b))
        buf.write(_ifd0_entry(0x0132, ASCII, len(dt_b), dt_b))

        # ExifIFD pointer - we'll patch this after
        exif_ifd_ptr_pos = buf.tell()
        buf.write(struct.pack("<HHI", 0x8769, LONG, 1) + b"\x00\x00\x00\x00")  # placeholder

        # Next IFD = 0 (no thumbnail)
        buf.write(struct.pack("<I", 0))

        # Write IFD0 data area
        buf.write(ifd0_data_area.getvalue())

        # --- ExifIFD ---
        exif_ifd_offset = buf.tell()

        # Patch the ExifIFD pointer in IFD0
        current_pos = buf.tell()
        buf.seek(exif_ifd_ptr_pos + 8)
        buf.write(struct.pack("<I", exif_ifd_offset))
        buf.seek(current_pos)

        exif_count = 9
        exif_entries_size = 2 + exif_count * 12 + 4
        exif_data_offset = exif_ifd_offset + exif_entries_size

        exif_data_area = io.BytesIO()

        def _exif_entry(tag: int, typ: int, count: int, value: bytes) -> bytes:
            if len(value) <= 4:
                return struct.pack("<HHI", tag, typ, count) + value.ljust(4, b"\x00")
            offset = exif_data_offset + exif_data_area.tell()
            exif_data_area.write(value)
            return struct.pack("<HHI", tag, typ, count) + struct.pack("<I", offset)

        buf.write(struct.pack("<H", exif_count))

        buf.write(_exif_entry(0x829A, RATIONAL, 1, exposure))          # ExposureTime
        buf.write(_exif_entry(0x829D, RATIONAL, 1, fnum_r))            # FNumber
        buf.write(_exif_entry(0x8827, SHORT, 1, struct.pack("<H", iso)))  # ISO
        buf.write(_exif_entry(0x9000, 7, 4, b"0232"))                  # ExifVersion
        buf.write(_exif_entry(0x9003, ASCII, len(dt_b), dt_b))         # DateTimeOriginal
        buf.write(_exif_entry(0x9004, ASCII, len(dt_b), dt_b))         # DateTimeDigitized
        buf.write(_exif_entry(0x920A, RATIONAL, 1, focal_r))           # FocalLength
        buf.write(_exif_entry(0xA002, LONG, 1, struct.pack("<I", width)))   # PixelXDimension
        buf.write(_exif_entry(0xA003, LONG, 1, struct.pack("<I", height)))  # PixelYDimension

        # Next IFD = 0
        buf.write(struct.pack("<I", 0))

        # Write ExifIFD data area
        buf.write(exif_data_area.getvalue())

        return buf.getvalue()

    @staticmethod
    def _patch_jpeg_exif(file_path: Path, tiff_data: bytes) -> None:
        """将 EXIF TIFF 数据作为 APP1 段插入 JPEG 文件头"""
        raw = file_path.read_bytes()
        if raw[:2] != b"\xff\xd8":
            logger.warning("非 JPEG 文件，跳过 EXIF 注入: %s", file_path.name)
            return

        # APP1 segment: FF E1 + length(2) + "Exif\0\0" + TIFF data
        exif_header = b"Exif\x00\x00"
        payload = exif_header + tiff_data
        app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload

        # Insert APP1 right after SOI (FF D8)
        # Skip any existing APP0 (JFIF) segment
        pos = 2
        if raw[2:4] == b"\xff\xe0":
            # Skip APP0
            app0_len = struct.unpack(">H", raw[4:6])[0]
            pos = 2 + 2 + app0_len

        patched = raw[:pos] + app1 + raw[pos:]
        file_path.write_bytes(patched)

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
