"""Long-form article content agent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from ....config.settings import ReviewConfig, RetryConfig
from ....core.base_agent import BaseAgent, ValidationResult
from ....utils.logger import get_logger
from ....utils.providers import get_text_model
from ..schemas import (
    ArticleBlock,
    ArticleBlockType,
    ArticleResearchResult,
    ArticleStrategy,
    XHSArticleContent,
)
from .prompts import (
    content_revision_user_prompt,
    content_system_prompt,
    content_user_prompt,
)
from .state import ContentState
from .tools import EvidenceReader
from .validator import ContentReviewValidator

logger = get_logger(__name__)


class ContentAgent(BaseAgent):
    role = "长文创作者"
    goal = "基于深度研究创作可发布的小红书长文"
    MAX_HISTORY_ROUNDS = 1

    def __init__(self, max_iterations: int | None = None):
        self.max_iterations = max_iterations or min(ReviewConfig.MAX_ITERATIONS, 13)
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
            prompt = content_revision_user_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                strategy=state.strategy.value,
                generate_images=state.generate_images,
                research_json=state.research.model_dump_json(indent=2),
                previous_draft_json=state.current_content.model_dump_json(indent=2) if state.current_content else "{}",
                feedback=state.last_feedback or "请补齐结构问题并输出完整长文。",
            )

        history = state.get_recent_history(self.MAX_HISTORY_ROUNDS)
        run_result = await self.generator.run(prompt, message_history=history)
        content = run_result.output
        content.strategy = state.strategy
        if state.strategy == ArticleStrategy.SYNTHESIZE:
            content.attribution_line = ""
            content.primary_source_ref = ""
        self._ensure_closing(content, state.topic)
        self._normalize_source_refs(content, state.research)
        self._inject_missing_image_slots(content, state.generate_images)
        content.rendered_body = self._render_body(content)
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
        if not output.closing or not output.closing.strip():
            return ValidationResult.failure("缺少单独的 closing 结尾字段")
        if not output.rendered_body:
            return ValidationResult.failure("缺少渲染后的正文")

        review_result = await self.review_validator.validate(
            output,
            context={
                "research_json": self._current_state.research.model_dump_json(indent=2),
                "generate_images": self._current_state.generate_images,
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
        # 话题不拼接到正文中，通过"# 话题"按钮在发布时单独添加
        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def _ensure_closing(content: XHSArticleContent, topic: str) -> None:
        content.closing = content.closing.strip()
        if content.closing:
            return

        normalized_topic = topic.strip() or content.title.strip()
        if normalized_topic:
            content.closing = (
                f"看到关于「{normalized_topic}」的各种说法时，真正值得留下的，"
                "不是照搬一种标准答案，而是把前面的信息变成你自己的判断。"
            )
        else:
            content.closing = "真正值得留下的，不是照搬一种标准答案，而是把前面的信息变成你自己的判断。"

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

    @staticmethod
    def _normalize_source_refs(
        content: XHSArticleContent,
        research: ArticleResearchResult,
    ) -> None:
        available_refs = ContentAgent._collect_available_source_refs(research)
        if not available_refs:
            return

        min_refs = 2 if content.strategy == ArticleStrategy.SYNTHESIZE and len(available_refs) > 1 else 1
        if content.strategy != ArticleStrategy.SYNTHESIZE and not content.primary_source_ref:
            content.primary_source_ref = research.primary_source_ref or available_refs[0]

        for idx, section in enumerate(content.sections):
            seed_refs = list(section.source_refs)
            for block in section.blocks:
                seed_refs.extend(block.source_refs)

            ranked_refs = ContentAgent._rank_source_refs_for_section(section, research, available_refs)
            section_refs = ContentAgent._fill_source_refs(
                seed_refs + ranked_refs,
                available_refs,
                minimum=min_refs,
                seed=idx,
            )
            section.source_refs = section_refs

            for block in section.blocks:
                block_refs = ContentAgent._fill_source_refs(
                    block.source_refs or section_refs,
                    available_refs,
                    minimum=min_refs if content.strategy == ArticleStrategy.SYNTHESIZE else 1,
                    seed=idx,
                )
                block.source_refs = block_refs

    @staticmethod
    def _collect_available_source_refs(research: ArticleResearchResult) -> list[str]:
        refs: list[str] = []
        for claim in research.claims:
            refs.extend(claim.source_refs)
        refs.extend(source.source_ref for source in research.sources)
        return ContentAgent._clean_source_refs(refs, refs)

    @staticmethod
    def _rank_source_refs_for_section(
        section: Any,
        research: ArticleResearchResult,
        available_refs: list[str],
    ) -> list[str]:
        section_text = "\n".join(
            [
                section.heading,
                section.summary,
                *(block.text for block in section.blocks if block.text),
                *(
                    item
                    for block in section.blocks
                    for item in block.items
                ),
            ]
        ).lower()
        section_terms = ContentAgent._extract_terms(section_text)
        source_order = {ref: idx for idx, ref in enumerate(available_refs)}
        scores: dict[str, float] = {}

        for claim in research.claims:
            claim_refs = ContentAgent._clean_source_refs(claim.source_refs, available_refs)
            if not claim_refs:
                continue

            claim_text = " ".join([claim.claim, claim.detail, claim.section_hint]).lower()
            overlap = len(section_terms & ContentAgent._extract_terms(claim_text))
            hint_bonus = 3.0 if claim.section_hint and claim.section_hint.lower() in section_text else 0.0
            if overlap == 0 and hint_bonus == 0.0:
                continue

            score = overlap * 4.0 + hint_bonus
            for ref in claim_refs:
                scores[ref] = scores.get(ref, 0.0) + score

        for source in research.sources:
            overlap = len(
                section_terms
                & ContentAgent._extract_terms(f"{source.title} {source.domain}".lower())
            )
            if overlap:
                scores[source.source_ref] = scores.get(source.source_ref, 0.0) + overlap

        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], source_order.get(item[0], len(source_order))),
        )
        return [ref for ref, _ in ranked]

    @staticmethod
    def _fill_source_refs(
        refs: list[str],
        available_refs: list[str],
        *,
        minimum: int,
        seed: int,
    ) -> list[str]:
        cleaned = ContentAgent._clean_source_refs(refs, available_refs)
        if len(cleaned) >= minimum:
            return cleaned[:3]

        if not available_refs:
            return cleaned

        offset = seed % len(available_refs)
        rotated = available_refs[offset:] + available_refs[:offset]
        for ref in rotated:
            if ref in cleaned:
                continue
            cleaned.append(ref)
            if len(cleaned) >= minimum:
                break
        return cleaned[:3]

    @staticmethod
    def _clean_source_refs(values: list[str], available_refs: list[str]) -> list[str]:
        allowed = {ref for ref in available_refs if ref}
        seen: set[str] = set()
        result: list[str] = []
        for ref in values:
            cleaned = str(ref).strip()
            if not cleaned or cleaned not in allowed or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
        return result

    @staticmethod
    def _extract_terms(text: str) -> set[str]:
        return {
            item
            for item in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)
            if len(item) > 1
        }
