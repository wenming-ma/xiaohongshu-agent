from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import CoverImageResult, XHSVideoContent
from ...shared.utils.image_postprocess import finalize_generated_image
from ....utils.providers import VertexAIImageClient, get_text_model
from ..utils.video_frames import extract_frames
from ....utils.logger import get_logger
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
        self.image_client = VertexAIImageClient(aspect_ratio="16:9")

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

            # Step 3: 生成封面图
            cover_path = output_dir / "cover.png"
            cover_path = await self.image_client.generate_image(
                prompt=prompt,
                output_path=cover_path,
                aspect_ratio="16:9",
                reference_images=frames,
            )
            cover_path = await finalize_generated_image(cover_path)

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
