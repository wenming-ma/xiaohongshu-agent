from __future__ import annotations

from pathlib import Path

from .image_sanitizer import sanitize_image
from .watermark_remover import remove_gemini_watermark
from ....utils.logger import get_logger

logger = get_logger(__name__)


async def finalize_generated_image(image_path: Path) -> Path:
    try:
        remove_gemini_watermark(image_path)
    except Exception as exc:
        logger.warning("去可见水印失败，继续使用原图: %s", exc)

    try:
        return await sanitize_image(image_path)
    except Exception as exc:
        logger.warning("图片后处理失败，继续使用原图: %s", exc)
        return image_path
