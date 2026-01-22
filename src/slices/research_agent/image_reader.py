"""
读图（OCR/视觉理解）Agent

目标：
- 以 Tool 的形式提供给其它 Agent（如 Research/Search）调用
- 使用 Claude 视觉模型进行图片理解
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent, Tool, BinaryContent

from ...models.schemas import ImageReadResult
from ...utils.image_compression import compress_image_for_review
from ...utils.logger import get_logger
from ...config.settings import RetryConfig, APIConfig
from ...utils.anthropic_provider import get_anthropic_model
from .prompts import image_reader_system_prompt, image_reader_user_prompt

logger = get_logger(__name__)


class ImageReaderAgent:
    """读图 Agent（输出结构化的 ImageReadResult），并提供 Tool 包装。"""

    def __init__(self):
        # 视觉任务使用 Claude 模型
        self._agent = Agent(
            model=get_anthropic_model(APIConfig.CLAUDE_IMAGE_MODEL),
            output_type=ImageReadResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_reader_system_prompt(),),
        )

    async def read_image(self, image_path: str, question: str = "") -> str:
        """
        读取图片内容（OCR + 轻量理解）。

        Args:
            image_path: 图片本地路径（png/jpg/webp 等）
            question: 可选问题（为空则仅做提取）

        Returns:
            ImageReadResult 的 JSON 字符串（便于其它 Agent/Tool 消费）
        """
        path = Path(image_path)
        if not path.exists():
            result = ImageReadResult(
                extracted_text="",
                description="",
                language="unknown",
                has_text=False,
                answer="",
                issues=[f"图片文件不存在: {image_path}"],
            )
            return result.model_dump_json(indent=2)

        # 压缩图片（API 限制 5MB）
        image_data = await compress_image_for_review(path, max_size_mb=5.0)

        # question 为空时也传入模板，便于 LLM 明确“忽略空问题”
        user_prompt = image_reader_user_prompt(question=(question or "").strip())

        logger.debug("ImageReaderAgent: reading image %s (question=%s)", path.name, bool(question))

        r = await self._agent.run(
            [
                user_prompt,
                BinaryContent(data=image_data, media_type="image/jpeg"),
            ]
        )

        return r.output.model_dump_json(indent=2)

    def get_tool(self) -> Tool:
        """获取可供其它 Agent 使用的 Tool。"""
        return Tool(self.read_image, takes_ctx=False)

