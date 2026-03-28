"""Deterministic Gemini Web cover generator.

This wraps the direct Playwright-based GeminiWebImageClient so the cover
pipeline no longer depends on an LLM browser agent to save generated images.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....config.settings import PathConfig
from ....core.base_agent import BaseAgent, ValidationResult
from ....utils.logger import get_logger
from ....utils.providers import GeminiWebImageClient
from ...shared.utils.image_sanitizer import sanitize_image
from ...shared.utils.watermark_remover import remove_gemini_watermark
from ..schemas import CoverImageResult

logger = get_logger(__name__)


class GeminiWebAgent(BaseAgent):

    role = "Gemini Web 图片生成操作员"
    goal = "通过确定性的浏览器自动化在 Gemini 网页上生成并下载图片"

    def __init__(self, output_dir: Path | None = None):
        self._output_dir = output_dir or PathConfig.DOWNLOADS_DIR
        super().__init__()

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        self.client = GeminiWebImageClient(browser_session_dir=PathConfig.BROWSER_SESSION_GEMINI)

    async def forward(
        self,
        prompt: str,
        output_path: Path,
        reference_images: list[Path] | None = None,
    ) -> CoverImageResult:
        logger.info("[GeminiWebAgent] 开始生成图片: %s", output_path.name)

        if reference_images:
            valid = [path for path in reference_images if path.exists()]
            if valid:
                logger.info("[GeminiWebAgent] 附加 %d 张参考图片", len(valid))

        try:
            raw_path = await self.client.generate_image(
                prompt=prompt,
                output_path=output_path,
                aspect_ratio="16:9",
                reference_images=reference_images,
            )
            final_path = await self._post_process_saved_image(raw_path)
        except Exception as exc:
            logger.warning("[GeminiWebAgent] 封面生成失败: %s", exc)
            return CoverImageResult(success=False, error_message=str(exc))

        if not final_path.exists() or final_path.stat().st_size <= 0:
            return CoverImageResult(success=False, error_message="封面文件不存在或为空")

        logger.info("[GeminiWebAgent] 封面生成成功: %s", final_path.name)
        return CoverImageResult(success=True, cover_path=str(final_path))

    async def step(self, *args, **kwargs):
        raise NotImplementedError("GeminiWebAgent 使用确定性客户端，不提供 step()")

    async def validate(self, output: Any) -> ValidationResult:
        if isinstance(output, CoverImageResult) and output.success:
            return ValidationResult.success("图片生成成功")
        msg = output.error_message if isinstance(output, CoverImageResult) else "输出类型错误"
        return ValidationResult.failure(msg)

    async def _post_process_saved_image(self, image_path: Path) -> Path:
        remove_gemini_watermark(image_path)
        logger.debug("[GeminiWebAgent] 去水印完成: %s", image_path.name)
        processed_path = await sanitize_image(image_path)
        logger.debug("[GeminiWebAgent] 去AI标记完成: %s", processed_path.name)
        return processed_path
