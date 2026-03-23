import base64
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart, ImageUrl

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import CoverImageResult, XHSVideoContent
from ....utils.providers import get_text_model, GeminiImageClient, GeminiWebImageClient
from ....utils.video_frames import extract_frames
from ....utils.logger import get_logger
from ....config.settings import APIConfig
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
        provider = APIConfig.GEMINI_IMAGE_PROVIDER
        if provider == "web":
            self.image_client = GeminiWebImageClient()
        elif provider == "api":
            self.image_client = GeminiImageClient(aspect_ratio="3:4")
        else:  # "auto": API 优先，失败回退 Web
            self.image_client = GeminiImageClient(aspect_ratio="3:4")
            self.web_image_client = GeminiWebImageClient()

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

            # Step 2: LLM 看截图 + 内容，生成封面 prompt
            prompt = await self._generate_cover_prompt(frames, content, topic)
            logger.info(f"封面 prompt: {prompt[:100]}...")

            # Step 3: Gemini 生成封面图（API 优先，失败回退 Web）
            cover_path = output_dir / "cover.png"
            try:
                await self.image_client.generate_image(
                    prompt=prompt,
                    output_path=cover_path,
                    aspect_ratio="3:4",
                    reference_images=frames,
                )
            except Exception as api_err:
                if hasattr(self, 'web_image_client'):
                    logger.warning(f"API 生成失败，降级到 Gemini Web: {api_err}")
                    await self.web_image_client.generate_image(
                        prompt=prompt,
                        output_path=cover_path,
                        aspect_ratio="3:4",
                        reference_images=frames,
                    )
                else:
                    raise

            if cover_path.exists() and cover_path.stat().st_size > 0:
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

    async def _generate_cover_prompt(
        self,
        frames: list[Path],
        content: XHSVideoContent,
        topic: str,
    ) -> str:
        """多模态 LLM 看截图 + 内容信息，生成封面图 prompt"""
        parts = []

        for frame in frames:
            b64 = base64.b64encode(frame.read_bytes()).decode()
            parts.append(ImageUrl(url=f"data:image/png;base64,{b64}"))

        text = cover_user_prompt(
            topic=topic,
            title=content.title,
            body=content.body[:200],
        )
        parts.append(UserPromptPart(content=text))

        result = await self.prompt_agent.run(
            [ModelRequest(parts=parts)]
        )
        return result.output.prompt
