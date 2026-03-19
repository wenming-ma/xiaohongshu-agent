"""Image generation agent for article posts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ....utils.logger import get_logger
from ....utils.providers import GeminiImageClient, GeminiWebImageClient, get_text_model
from ....config.settings import APIConfig
from ..schemas import (
    ArticleBlock,
    ArticleBlockType,
    ArticleImageResult,
    ArticleImageSpec,
    ArticleResearchResult,
    ArticleSection,
    GeneratedArticleImage,
    XHSArticleContent,
)
from .prompts import image_system_prompt, image_user_prompt

logger = get_logger(__name__)


def _is_retryable_error(e: Exception) -> bool:
    """判断是否为可降级到 Web 的可重试错误"""
    msg = str(e).lower()
    return any(kw in msg for kw in ("503", "unavailable", "overloaded", "timeout", "disconnected"))


class ImageAgent(BaseAgent):
    role = "长文配图设计师"
    goal = "为长文生成头图和章节配图"

    def init_tools(self) -> None:
        provider = APIConfig.GEMINI_IMAGE_PROVIDER
        if provider == "web":
            self.image_client = GeminiWebImageClient()
        elif provider == "api":
            self.image_client = GeminiImageClient(aspect_ratio="16:9")
        else:  # "auto"
            self.image_client = GeminiImageClient(aspect_ratio="16:9")
            self.web_image_client = GeminiWebImageClient()

    def init_agent(self) -> None:
        self.prompt_agent = Agent(
            model=get_text_model(),
            output_type=str,
            instrument=True,
            system_prompt=(image_system_prompt(),),
        )

    async def forward(
        self,
        content: XHSArticleContent,
        research: ArticleResearchResult,
        topic: str,
        target_audience: str,
        output_dir: Path,
    ) -> ArticleImageResult:
        specs = self._build_specs(content, research)
        generated: list[GeneratedArticleImage] = []
        for spec in specs:
            generated.append(
                await self.step(
                    content=content,
                    research=research,
                    topic=topic,
                    target_audience=target_audience,
                    output_dir=output_dir,
                    image_spec=spec,
                )
            )

        result = ArticleImageResult(
            images=generated,
            total_count=len(generated),
            generated_at=datetime.now().isoformat(),
        )
        validation = await self.validate(result)
        if not validation.passed:
            raise RuntimeError(validation.feedback)
        return result

    async def step(
        self,
        content: XHSArticleContent,
        research: ArticleResearchResult,
        topic: str,
        target_audience: str,
        output_dir: Path,
        image_spec: ArticleImageSpec,
    ) -> GeneratedArticleImage:
        prompt = await self.prompt_agent.run(
            image_user_prompt(
                topic=topic,
                title=content.title,
                target_audience=target_audience,
                image_key=image_spec.image_key,
                image_role=image_spec.image_role or image_spec.label,
                visual_goal=image_spec.visual_goal or "为长文生成一张具体、可读、可发布的配图",
                visual_direction=image_spec.visual_direction or "根据章节内容选择合适的视觉路线",
                article_outline=self._format_prompt_list(image_spec.article_outline),
                key_points=self._format_prompt_list(image_spec.key_points),
                text_lines=self._format_prompt_list(image_spec.text_lines),
                avoid_points=self._format_prompt_list(image_spec.avoid_points),
                context_text=image_spec.prompt_hint,
            )
        )
        output_path = output_dir / f"{image_spec.image_key}.png"
        try:
            image_path = await self.image_client.generate_image(prompt.output, output_path)
        except Exception as api_err:
            if hasattr(self, 'web_image_client') and _is_retryable_error(api_err):
                logger.warning("API 失败，降级到 Gemini Web: %s", api_err)
                image_path = await self.web_image_client.generate_image(prompt.output, output_path)
            else:
                raise
        return GeneratedArticleImage(
            image_key=image_spec.image_key,
            image_path=str(image_path),
            prompt_used=prompt.output,
        )

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, ArticleImageResult):
            return ValidationResult.failure("图片结果类型错误")
        if output.total_count == 0:
            return ValidationResult.failure("未生成任何配图")
        return ValidationResult.success(f"已生成 {output.total_count} 张配图")

    @staticmethod
    def _build_specs(
        content: XHSArticleContent,
        research: ArticleResearchResult,
    ) -> list[ArticleImageSpec]:
        article_outline = [
            f"第{idx}章：{section.heading.strip()}"
            for idx, section in enumerate(content.sections, start=1)
            if section.heading.strip()
        ]
        specs: list[ArticleImageSpec] = [
            ArticleImageSpec(
                image_key="cover",
                label="封面图",
                prompt_hint=ImageAgent._build_cover_context(content, research, article_outline),
                source_refs=[content.primary_source_ref] if content.primary_source_ref else [],
                image_role="整篇长文封面图",
                visual_goal="第一眼说明文章主题和收藏价值，同时保持女性用户更容易喜欢和收藏的专题封面气质",
                visual_direction=ImageAgent._infer_visual_direction(
                    heading=content.title,
                    summary=content.lead,
                    points=[section.heading for section in content.sections[:3]],
                    blocks=[],
                    is_cover=True,
                ),
                article_outline=article_outline[:5],
                key_points=ImageAgent._build_cover_key_points(content, research),
                text_lines=ImageAgent._build_cover_text_lines(content),
                avoid_points=[
                    "不要把整篇长文所有段落塞成满屏大字",
                    "不要出现来源链接、source_ref、英文长句或用户名",
                    "不要做成冷硬科技海报、企业汇报封面或男性向硬核器材风",
                    "不要只写“高质感、极简、大气”，必须有具体主体和版式",
                ],
            )
        ]
        for section in content.sections:
            section_spec = ImageAgent._build_section_spec(
                research=research,
                section=section,
                article_outline=article_outline,
            )
            if section_spec is None:
                continue
            specs.append(section_spec)
        deduped: list[ArticleImageSpec] = []
        seen_keys: set[str] = set()
        for spec in specs:
            if spec.image_key in seen_keys:
                continue
            seen_keys.add(spec.image_key)
            deduped.append(spec)
        return deduped

    @classmethod
    def _build_section_spec(
        cls,
        research: ArticleResearchResult,
        section: ArticleSection,
        article_outline: list[str],
    ) -> ArticleImageSpec | None:
        image_key = cls._find_section_image_key(section)
        if not image_key or image_key == "cover":
            return None

        visible_points = cls._collect_section_points(section)
        claim_clues = cls._collect_section_claims(section, research)
        source_clues = cls._collect_source_clues(section.source_refs, research)
        key_points = cls._dedupe_lines(
            [section.summary, *visible_points, *claim_clues],
            limit=5,
        )
        prompt_hint = cls._build_section_context(
            section=section,
            visible_points=visible_points,
            claim_clues=claim_clues,
            source_clues=source_clues,
        )
        return ArticleImageSpec(
            image_key=image_key,
            label=section.heading,
            prompt_hint=prompt_hint,
            source_refs=section.source_refs,
            image_role=f"章节配图：{section.heading}",
            visual_goal="帮助读者在进入这一章时迅速抓住核心观点，并保持女性向、精致、可收藏的整体视觉气质",
            visual_direction=cls._infer_visual_direction(
                heading=section.heading,
                summary=section.summary,
                points=key_points,
                blocks=section.blocks,
            ),
            article_outline=article_outline[:5],
            key_points=key_points,
            text_lines=cls._build_section_text_lines(section, key_points),
            avoid_points=[
                "不要重复整篇文章全部章节，只表达当前章节",
                "不要添加输入里没有的数据、结论或案例",
                "不要做成冷硬商务图表、男性向参数卡或新闻截图排版",
                "不要出现来源标题、source_ref、域名、评论区措辞",
            ],
        )

    @staticmethod
    def _find_section_image_key(section: ArticleSection) -> str:
        for block in section.blocks:
            if block.image_key:
                return block.image_key
        return ""

    @classmethod
    def _build_cover_context(
        cls,
        content: XHSArticleContent,
        research: ArticleResearchResult,
        article_outline: list[str],
    ) -> str:
        lines = [
            f"导语重点：{cls._clip_text(content.lead, 120)}",
            f"文章结构：{' / '.join(article_outline[:4]) or '无'}",
        ]
        if research.summary:
            lines.append(f"研究摘要：{cls._clip_text(research.summary, 140)}")
        if content.source_summary:
            lines.append(f"写作线索：{cls._clip_text(content.source_summary, 140)}")
        return "\n".join(lines)

    @classmethod
    def _build_section_context(
        cls,
        *,
        section: ArticleSection,
        visible_points: list[str],
        claim_clues: list[str],
        source_clues: list[str],
    ) -> str:
        lines = [
            f"章节标题：{section.heading}",
            f"章节摘要：{cls._clip_text(section.summary, 120) or '无'}",
        ]
        if visible_points:
            lines.append(f"正文要点：{' / '.join(visible_points[:4])}")
        if claim_clues:
            lines.append(f"研究支撑：{' / '.join(claim_clues[:3])}")
        if source_clues:
            lines.append(
                f"来源线索（仅理解用，不要出现在图中）：{' / '.join(source_clues[:3])}"
            )
        return "\n".join(lines)

    @classmethod
    def _build_cover_key_points(
        cls,
        content: XHSArticleContent,
        research: ArticleResearchResult,
    ) -> list[str]:
        section_hooks = [
            cls._clip_text(section.heading, 20)
            for section in content.sections[:3]
            if section.heading.strip()
        ]
        research_hook = cls._clip_text(research.summary, 60)
        return cls._dedupe_lines(
            [
                cls._clip_text(content.lead, 70),
                *section_hooks,
                research_hook,
            ],
            limit=5,
        )

    @classmethod
    def _build_cover_text_lines(cls, content: XHSArticleContent) -> list[str]:
        section_tags = [
            cls._clip_text(section.heading, 10)
            for section in content.sections[:2]
            if section.heading.strip()
        ]
        return cls._dedupe_lines([content.title, *section_tags], limit=3)

    @classmethod
    def _build_section_text_lines(
        cls,
        section: ArticleSection,
        key_points: list[str],
    ) -> list[str]:
        info_lines = [
            cls._clip_text(point, 18)
            for point in key_points
            if point and point != section.summary
        ]
        return cls._dedupe_lines([section.heading, *info_lines], limit=4)

    @classmethod
    def _collect_section_points(cls, section: ArticleSection) -> list[str]:
        points: list[str] = []
        if section.summary:
            points.append(cls._clip_text(section.summary, 60))
        for block in section.blocks:
            if block.block_type == ArticleBlockType.IMAGE_SLOT:
                continue
            points.extend(cls._extract_block_points(block))
        return cls._dedupe_lines(points, limit=6)

    @classmethod
    def _extract_block_points(cls, block: ArticleBlock) -> list[str]:
        if block.block_type in (ArticleBlockType.PARAGRAPH, ArticleBlockType.QUOTE, ArticleBlockType.HEADING):
            return cls._split_sentences(block.text, limit=2)
        if block.block_type in (ArticleBlockType.BULLET_LIST, ArticleBlockType.NUMBERED_LIST):
            return [
                cls._clip_text(item, 40)
                for item in block.items
                if item.strip()
            ][:4]
        return []

    @classmethod
    def _collect_section_claims(
        cls,
        section: ArticleSection,
        research: ArticleResearchResult,
    ) -> list[str]:
        section_text = "\n".join(
            [
                section.heading,
                section.summary,
                *(block.text for block in section.blocks if block.text),
                *(item for block in section.blocks for item in block.items),
            ]
        ).lower()
        section_terms = cls._extract_terms(section_text)
        ranked_claims: list[tuple[float, str]] = []
        section_refs = set(section.source_refs)

        for claim in research.claims:
            claim_text = " ".join([claim.claim, claim.detail, claim.section_hint]).strip()
            if not claim_text:
                continue

            score = 0.0
            if section_refs and section_refs.intersection(claim.source_refs):
                score += 3.0
            if claim.section_hint and claim.section_hint.lower() in section_text:
                score += 2.0
            overlap = len(section_terms & cls._extract_terms(claim_text.lower()))
            score += float(overlap)
            if score <= 0:
                continue
            ranked_claims.append((score, cls._clip_text(claim.claim or claim.detail, 50)))

        ranked_claims.sort(key=lambda item: item[0], reverse=True)
        return cls._dedupe_lines([text for _, text in ranked_claims], limit=3)

    @classmethod
    def _collect_source_clues(
        cls,
        source_refs: list[str],
        research: ArticleResearchResult,
    ) -> list[str]:
        source_map = {source.source_ref: source for source in research.sources}
        clues: list[str] = []
        for source_ref in source_refs:
            source = source_map.get(source_ref)
            if source is None:
                continue
            label = source.title or source.domain or source.source_ref
            clues.append(cls._clip_text(label, 50))
        return cls._dedupe_lines(clues, limit=3)

    @classmethod
    def _infer_visual_direction(
        cls,
        *,
        heading: str,
        summary: str,
        points: list[str],
        blocks: list[ArticleBlock],
        is_cover: bool = False,
    ) -> str:
        text = " ".join([heading, summary, *points]).lower()
        list_like = any(
            block.block_type in (ArticleBlockType.BULLET_LIST, ArticleBlockType.NUMBERED_LIST)
            for block in blocks
        )
        info_keywords = (
            "方法", "步骤", "清单", "建议", "指南", "对比", "预算", "框架", "误区",
            "关键词", "重点", "搭配", "策略", "趋势", "复盘",
        )
        scene_keywords = (
            "故事", "情绪", "氛围", "人物", "生活", "关系", "旅行", "家居", "风格",
            "感受", "穿搭", "场景", "治愈", "办公室", "通勤",
        )
        if is_cover:
            if any(keyword in text for keyword in info_keywords):
                return "女性向杂志感专题封面：一个强主标题，搭配 2-3 个章节标签或信息钩子，柔和配色、有留白，避免做成教材式流程图"
            if any(keyword in text for keyword in scene_keywords):
                return "女性向场景化 editorial 封面：一个能承载主题情绪的主场景或人物主体，配简短中文标题，整体像时尚杂志专题页"
            return "女性向概念拼贴封面：核心意象 + 中文标题 + 少量信息标签，整体像可收藏的专题海报"
        if list_like or any(keyword in text for keyword in info_keywords):
            return "女性向结构化章节图：用杂志内页、手账感信息卡或 lookbook 版式承载 2-4 个要点，强调层级、留白和柔和配色"
        if any(keyword in text for keyword in scene_keywords):
            return "女性向场景化章节图：用 editorial 场景、概念拼贴或插画表达本章氛围，仅保留少量中文点题"
        return "女性向概念化章节头图：一个核心主体 + 章节标题 + 2-3 个辅助标签，兼顾专题感、收藏感和可读性"

    @staticmethod
    def _extract_terms(text: str) -> set[str]:
        return {
            item
            for item in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)
            if len(item) > 1
        }

    @classmethod
    def _split_sentences(cls, text: str, limit: int = 2) -> list[str]:
        if not text.strip():
            return []
        sentences = re.split(r"[。！？；\n]+", text)
        cleaned = [
            cls._clip_text(sentence, 40)
            for sentence in sentences
            if sentence.strip()
        ]
        return cleaned[:limit]

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return ""
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: max(limit - 1, 1)].rstrip("，、；：,. ") + "…"

    @classmethod
    def _dedupe_lines(cls, lines: list[str], limit: int) -> list[str]:
        seen: set[str] = set()
        results: list[str] = []
        for line in lines:
            cleaned = " ".join(str(line).split()).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            results.append(cleaned)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _format_prompt_list(items: list[str]) -> str:
        if not items:
            return "- 无"
        return "\n".join(f"- {item}" for item in items if item)
