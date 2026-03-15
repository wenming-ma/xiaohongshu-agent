"""Publisher agent for Xiaohongshu long-form articles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from .....config.settings import PathConfig, PublishConfig, RetryConfig
from .....core.base_agent import BaseAgent, ValidationResult
from .....utils.logger import get_logger
from .....utils.providers import get_text_model
from .....utils.retry_handler import with_retry
from ...shared import create_shared_playwright_mcp_server
from ...shared.login import create_login_tool
from ..schemas import ArticleBlockType, ArticlePublishResult, ArticleSection, XHSArticleContent
from .prompts import publish_system_prompt, publish_user_prompt

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

    def init_agent(self) -> None:
        self.publisher = Agent(
            model=get_text_model(),
            output_type=ArticlePublishResult,
            toolsets=[self.mcp_server],
            tools=[self.login_tool],
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
        hashtags_str = "\n".join([f"   - {tag}" for tag in content.hashtags]) if content.hashtags else "无"
        result = await self.step(
            publish_user_prompt(
                title=content.title,
                body=content.rendered_body,
                hashtags=hashtags_str,
                images=self._format_images(images),
                image_plan=self._build_image_plan(content, images),
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
    def _build_image_plan(cls, content: XHSArticleContent, images: list[Path]) -> str:
        if not images:
            return "无图片，无需插图计划"

        images_by_key = {path.stem: path for path in images}
        used_keys: set[str] = set()
        lines: list[str] = []

        for section in content.sections:
            for block_index, block in enumerate(section.blocks):
                if block.block_type != ArticleBlockType.IMAGE_SLOT or not block.image_key:
                    continue
                image_path = images_by_key.get(block.image_key)
                if not image_path:
                    continue
                used_keys.add(block.image_key)
                anchor = cls._describe_image_anchor(section, block_index, block.image_key)
                lines.append(f"{len(lines) + 1}. {block.image_key}: {image_path} -> {anchor}")

        for image_path in images:
            if image_path.stem in used_keys:
                continue
            lines.append(
                f"{len(lines) + 1}. {image_path.stem}: {image_path} -> "
                "如果没有明确锚点，把它插在最接近主题的小节末尾，单独成段。"
            )

        return "\n".join(lines)

    @classmethod
    def _describe_image_anchor(
        cls,
        section: ArticleSection,
        block_index: int,
        image_key: str,
    ) -> str:
        previous_text = cls._find_nearby_text(section, block_index, reverse=True)
        next_text = cls._find_nearby_text(section, block_index, reverse=False)

        if image_key == "cover":
            return f"在章节《{section.heading}》开头附近插入，优先放在该章节第一段前。"
        if previous_text:
            return f"在章节《{section.heading}》内，紧跟“{previous_text}”之后插入。"
        if next_text:
            return f"在章节《{section.heading}》内，放在“{next_text}”之前插入。"
        return f"在章节《{section.heading}》内单独成段插入。"

    @staticmethod
    def _find_nearby_text(section: ArticleSection, block_index: int, *, reverse: bool) -> str:
        indices = range(block_index - 1, -1, -1) if reverse else range(block_index + 1, len(section.blocks))
        for idx in indices:
            block = section.blocks[idx]
            if block.block_type == ArticleBlockType.IMAGE_SLOT:
                continue
            if block.text.strip():
                return PublisherAgent._truncate_anchor(block.text)
            for item in block.items:
                if item.strip():
                    return PublisherAgent._truncate_anchor(item)
        return ""

    @staticmethod
    def _truncate_anchor(text: str, limit: int = 24) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 1]}…"
