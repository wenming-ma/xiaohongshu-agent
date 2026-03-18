"""Publisher agent for Xiaohongshu long-form articles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ....config.settings import PathConfig, PublishConfig, RetryConfig
from ....core.base_agent import BaseAgent, ValidationResult
from ....utils.logger import get_logger
from ....utils.providers import get_text_model
from ....utils.retry_handler import with_retry
from ...shared import create_shared_playwright_mcp_server
from ...shared.login import create_login_tool
from ..schemas import ArticleBlockType, ArticlePublishResult, XHSArticleContent
from .prompts import publish_system_prompt, publish_user_prompt
from .tools import create_article_publish_tools

logger = get_logger(__name__)


class PublisherAgent(BaseAgent):
    role = "长文发布专员"
    goal = "把长文发布到小红书长文编辑器"

    def __init__(self):
        self.init_mcp_server()
        super().__init__()

    def init_mcp_server(self) -> None:
        self.mcp_server = create_shared_playwright_mcp_server(
            output_dir=PathConfig.DOWNLOADS_DIR,
            tool_prefix="playwright",
            headless=False,
        )

    def init_tools(self) -> None:
        self.login_tool = create_login_tool(self.mcp_server)
        self.publish_tools = create_article_publish_tools(self.mcp_server)

    def init_agent(self) -> None:
        self.publisher = Agent(
            model=get_text_model(),
            output_type=ArticlePublishResult,
            toolsets=[self.mcp_server],
            tools=[self.login_tool, *self.publish_tools.get_tools()],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(publish_system_prompt(),),
        )

    @with_retry(max_retries=PublishConfig.MAX_RETRIES, initial_delay=PublishConfig.INITIAL_DELAY)
    async def forward(
        self,
        content: XHSArticleContent,
        images: list[Path],
        output_dir: Path,
    ) -> ArticlePublishResult:
        logger.info("准备发布长文: %s", content.title)
        self.publish_tools.bind_content(content)
        self.publish_tools.bind_images(self._build_image_slot_plan(content, images))
        hashtags_str = "\n".join([f"   - {tag}" for tag in content.hashtags]) if content.hashtags else "无"
        result = await self.step(
            publish_user_prompt(
                title=content.title,
                body=content.rendered_body,
                hashtags=hashtags_str,
                images=self._format_images(images),
            )
        )
        result.image_paths = [str(path) for path in images]
        validation = await self.validate(result)
        if not validation.passed:
            raise RuntimeError(validation.feedback)
        return result

    async def step(self, user_prompt: str) -> ArticlePublishResult:
        async with self.mcp_server:
            result = await self.publisher.run(
                user_prompt,
                usage_limits=UsageLimits(request_limit=None),
            )
            return result.output

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, ArticlePublishResult):
            return ValidationResult.failure("发布结果类型错误")
        if output.published:
            return ValidationResult.success(output.post_url or "长文已发布")
        return ValidationResult.failure(output.error_message or "长文发布失败")

    @staticmethod
    def _format_images(images: list[Path]) -> str:
        if not images:
            return "无图片，发布纯文字长文"
        return "\n".join(f"{idx + 1}. {path.stem}: {path}" for idx, path in enumerate(images))

    @classmethod
    def _build_image_slot_plan(cls, content: XHSArticleContent, images: list[Path]) -> list[tuple[str, Path]]:
        """Build ordered (slot_key, file_path) pairs for deterministic upload."""
        if not images:
            return []
        images_by_key = {path.stem: path for path in images}
        plan: list[tuple[str, Path]] = []
        for section in content.sections:
            for block in section.blocks:
                if block.block_type != ArticleBlockType.IMAGE_SLOT or not block.image_key:
                    continue
                image_path = images_by_key.get(block.image_key)
                if image_path:
                    plan.append((block.image_key, image_path))
        # Append images without matching slots
        used_keys = {key for key, _ in plan}
        for image_path in images:
            if image_path.stem not in used_keys:
                plan.append((image_path.stem, image_path))
        return plan

