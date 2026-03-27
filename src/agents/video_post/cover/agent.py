from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import CoverImageResult, XHSVideoContent
from ....utils.providers import get_text_model, GeminiImageClient
from ....utils.watermark_remover import remove_gemini_watermark
from ....utils.image_sanitizer import sanitize_image
from ....utils.video_frames import extract_frames
from ....utils.logger import get_logger
from ....config.settings import APIConfig
from .gemini_web_agent import GeminiWebAgent
from .prompts import cover_system_prompt, cover_user_prompt

logger = get_logger(__name__)


class CoverPromptResult(BaseModel):
    prompt: str


class CoverAgent(BaseAgent):

    role = "视频封面设计师"
    goal = "为小红书视频生成吸引眼球的封面图"

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        self.prompt_agent = Agent(
            model=get_text_model(),
            output_type=CoverPromptResult,
            system_prompt=(cover_system_prompt(),),
        )
        self._use_api = False
        self._use_web_fallback = False
        provider = APIConfig.GEMINI_IMAGE_PROVIDER
        if provider == "web":
            pass
        elif provider == "api":
            self._use_api = True
        else:  # "auto": API 优先，失败回退 Web Agent
            self._use_api = True
            self._use_web_fallback = True

        if self._use_api:
            self.image_client = GeminiImageClient(aspect_ratio="16:9")

    async def forward(
        self,
        video_path: Path,
        content: XHSVideoContent,
        topic: str,
        output_dir: Path,
    ) -> CoverImageResult:
        logger.info("开始生成视频封面...")

        try:
            # Step 1: 截取关键帧
            frames = await extract_frames(video_path, output_dir)

            # Step 2: LLM 根据文字信息生成封面 prompt
            prompt = await self._generate_cover_prompt(content, topic)
            logger.info(f"封面 prompt: {prompt[:100]}...")

            # Step 3: Gemini 生成封面图
            cover_path = output_dir / "cover.png"

            if self._use_api:
                try:
                    await self.image_client.generate_image(
                        prompt=prompt,
                        output_path=cover_path,
                        aspect_ratio="16:9",
                        reference_images=frames,
                    )
                except Exception as api_err:
                    if getattr(self, '_use_web_fallback', False):
                        logger.warning(f"API 生成失败，降级到 Gemini Web Agent: {api_err}")
                        return await self._run_web_agent(prompt, cover_path, frames)
                    raise
            else:
                return await self._run_web_agent(prompt, cover_path, frames)

            if cover_path.exists() and cover_path.stat().st_size > 0:
                cover_path = await self._post_process(cover_path)
                logger.info(f"封面生成成功: {cover_path}")
                return CoverImageResult(success=True, cover_path=str(cover_path))
            else:
                return CoverImageResult(success=False, error_message="封面文件为空")

        except Exception as e:
            logger.warning(f"封面生成失败: {e}")
            return CoverImageResult(success=False, error_message=str(e))
        finally:
            # 清理截帧临时文件
            for f in output_dir.glob("frame_*.png"):
                f.unlink(missing_ok=True)

    async def step(self, *args, **kwargs):
        pass

    async def validate(self, output) -> ValidationResult:
        if isinstance(output, CoverImageResult) and output.success:
            return ValidationResult.success("封面生成成功")
        return ValidationResult.failure("封面生成失败")

    async def _run_web_agent(
        self,
        prompt: str,
        cover_path: Path,
        reference_images: list[Path],
    ) -> CoverImageResult:
        web_agent = GeminiWebAgent(output_dir=cover_path.parent)
        result = await web_agent.forward(
            prompt=prompt,
            output_path=cover_path,
            reference_images=reference_images,
        )
        if result.success and cover_path.exists():
            processed = await self._post_process(cover_path)
            result.cover_path = str(processed)
        return result

    async def _post_process(self, image_path: Path) -> Path:
        try:
            remove_gemini_watermark(image_path)
            logger.debug("去水印完成: %s", image_path.name)
        except Exception as e:
            logger.warning("去水印失败: %s", e)
        from ....config.settings import SanitizerConfig
        if SanitizerConfig.ENABLED:
            try:
                image_path = await sanitize_image(image_path)
                logger.debug("去AI标记完成: %s", image_path.name)
            except Exception as e:
                logger.warning("去AI标记失败: %s", e)
        return image_path

    async def _generate_cover_prompt(
        self,
        content: XHSVideoContent,
        topic: str,
    ) -> str:
        """LLM 根据文字信息生成封面图 prompt（截图只作为 Gemini 图片生成的参考）"""
        prompt = cover_user_prompt(
            topic=topic,
            title=content.title,
            body=content.body[:200],
        )
        result = await self.prompt_agent.run(prompt)
        return result.output.prompt
