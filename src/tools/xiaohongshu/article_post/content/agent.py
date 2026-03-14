"""Long-form article content agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from .....config.settings import ReviewConfig, RetryConfig
from .....core.base_agent import BaseAgent, ValidationResult
from .....utils.logger import get_logger
from .....utils.providers import get_text_model
from ..schemas import (
    ArticleBlock,
    ArticleBlockType,
    ArticleResearchResult,
    ArticleStrategy,
    XHSArticleContent,
)
from .prompts import content_system_prompt, content_user_prompt
from .state import ContentState
from .tools import EvidenceReader
from .validator import ContentReviewValidator

logger = get_logger(__name__)


class ContentAgent(BaseAgent):
    role = "长文创作者"
    goal = "基于深度研究创作可发布的小红书长文"

    def __init__(self, max_iterations: int | None = None):
        self.max_iterations = max_iterations or min(ReviewConfig.MAX_ITERATIONS, 4)
        super().__init__()
        self.init_validators()

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        # Generator is lazily created in forward() when output_dir is known,
        # so we only build a default here as fallback.
        self.generator = self._build_generator()

    def init_validators(self) -> None:
        self.review_validator = ContentReviewValidator()

    def _build_generator(self, output_dir: Path | None = None) -> Agent:
        model = get_text_model()
        tools = []
        if output_dir and (output_dir / "source_index.json").exists():
            reader = EvidenceReader(output_dir)
            tools = reader.get_tools()
            logger.info("已注册 EvidenceReader 工具 (%d 个)", len(tools))
        return Agent(
            model=model,
            output_type=XHSArticleContent,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(content_system_prompt(),),
            tools=tools,
        )

    async def forward(
        self,
        research: ArticleResearchResult,
        topic: str,
        target_audience: str,
        requested_strategy: ArticleStrategy,
        generate_images: bool,
        output_dir: Path | None = None,
    ) -> XHSArticleContent:
        # Rebuild generator with evidence tools when output_dir is available
        if output_dir:
            self.generator = self._build_generator(output_dir)

        strategy = self._resolve_strategy(research, requested_strategy)
        state = ContentState(
            research=research,
            topic=topic,
            target_audience=target_audience,
            strategy=strategy,
            generate_images=generate_images,
            output_dir=output_dir,
        )

        logger.info("开始长文创作: %s (%s)", topic, strategy.value)

        for iteration in range(self.max_iterations):
            await self.step(state, iteration)
            validation = await self.validate(state.current_content)
            if validation.passed:
                logger.info("长文审核通过 (%d/%d)", iteration + 1, self.max_iterations)
                return state.current_content
            self.on_validation_failed(state, validation.feedback)

        logger.warning("长文达到最大迭代次数，返回最后一版内容")
        return state.current_content

    async def step(self, state: ContentState, iteration: int) -> None:
        if iteration == 0:
            prompt = content_user_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                strategy=state.strategy.value,
                generate_images=state.generate_images,
                research_json=state.research.model_dump_json(indent=2),
            )
        else:
            prompt = "请根据上轮反馈修订结构、署名和事实支撑，保持适合小红书长文的中文表达。"

        run_result = await self.generator.run(
            prompt,
            message_history=state.get_recent_history(6),
        )
        content = run_result.output
        content.strategy = state.strategy
        content.rendered_body = self._render_body(content)
        self._inject_missing_image_slots(content, state.generate_images)

        state.current_content = content
        state.message_history.extend(run_result.new_messages())
        self._current_state = state

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, XHSArticleContent):
            return ValidationResult.failure("输出类型错误，期望 XHSArticleContent")
        if not output.title or not output.lead:
            return ValidationResult.failure("缺少标题或导语")
        if len(output.sections) < 3:
            return ValidationResult.failure("章节数量不足，至少需要 3 个章节")
        if output.strategy in (ArticleStrategy.REPURPOSE_ARTICLE, ArticleStrategy.REPURPOSE_VIDEO) and not output.attribution_line:
            return ValidationResult.failure("搬运路径缺少明确署名")
        if not output.rendered_body:
            return ValidationResult.failure("缺少渲染后的正文")

        review_result = await self.review_validator.validate(
            output,
            context={
                "research_json": self._current_state.research.model_dump_json(indent=2),
                "output_dir": self._current_state.output_dir,
            },
        )

        if review_result.passed:
            return ValidationResult.success(f"审核通过，评分 {review_result.score:.1f}")
        return ValidationResult.failure(review_result.feedback)

    def on_validation_failed(self, state: ContentState, feedback: str) -> None:
        logger.warning("长文审核未通过: %s", feedback[:200])
        state.inject_feedback(feedback)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_strategy(
        research: ArticleResearchResult,
        requested_strategy: ArticleStrategy,
    ) -> ArticleStrategy:
        if requested_strategy != ArticleStrategy.AUTO:
            return requested_strategy
        return research.suggested_strategy or ArticleStrategy.SYNTHESIZE

    @staticmethod
    def _render_body(content: XHSArticleContent) -> str:
        lines: list[str] = [content.lead.strip()]
        if content.attribution_line:
            lines.append(content.attribution_line.strip())
        for section in content.sections:
            lines.append(f"\n{section.heading.strip()}")
            if section.summary:
                lines.append(section.summary.strip())
            for block in section.blocks:
                if block.block_type == ArticleBlockType.HEADING and block.text:
                    lines.append(block.text.strip())
                elif block.block_type == ArticleBlockType.PARAGRAPH and block.text:
                    lines.append(block.text.strip())
                elif block.block_type == ArticleBlockType.QUOTE and block.text:
                    lines.append(f"「{block.text.strip()}」")
                elif block.block_type in (ArticleBlockType.BULLET_LIST, ArticleBlockType.NUMBERED_LIST):
                    for idx, item in enumerate(block.items, start=1):
                        prefix = f"{idx}." if block.block_type == ArticleBlockType.NUMBERED_LIST else "- "
                        lines.append(f"{prefix} {item.strip()}")
        if content.closing:
            lines.append(f"\n{content.closing.strip()}")
        if content.hashtags:
            lines.append(" ".join(f"#{tag}" for tag in content.hashtags))
        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def _inject_missing_image_slots(content: XHSArticleContent, generate_images: bool) -> None:
        if not generate_images:
            return
        for idx, section in enumerate(content.sections, start=1):
            has_slot = any(block.block_type == ArticleBlockType.IMAGE_SLOT for block in section.blocks)
            if has_slot:
                continue
            section.blocks.append(
                ArticleBlock(
                    block_type=ArticleBlockType.IMAGE_SLOT,
                    image_key="cover" if idx == 1 else f"section_{idx}",
                    source_refs=section.source_refs,
                )
            )
