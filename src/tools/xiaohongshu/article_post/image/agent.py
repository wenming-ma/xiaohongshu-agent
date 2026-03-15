"""Image generation agent for article posts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from .....core.base_agent import BaseAgent, ValidationResult
from .....utils.logger import get_logger
from .....utils.providers import GeminiImageClient, get_text_model
from ..schemas import (
    ArticleImageResult,
    ArticleImageSpec,
    ArticleResearchResult,
    GeneratedArticleImage,
    XHSArticleContent,
)
from .prompts import image_system_prompt, image_user_prompt

logger = get_logger(__name__)


class ImageAgent(BaseAgent):
    role = "长文配图设计师"
    goal = "为长文生成头图和章节配图"

    def init_tools(self) -> None:
        self.image_client = GeminiImageClient()

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
        output_dir: Path,
        image_spec: ArticleImageSpec,
    ) -> GeneratedArticleImage:
        prompt = await self.prompt_agent.run(
            image_user_prompt(
                topic=topic,
                title=content.title,
                label=image_spec.label,
                image_key=image_spec.image_key,
                context_text=image_spec.prompt_hint,
            )
        )
        output_path = output_dir / f"{image_spec.image_key}.png"
        image_path = await self.image_client.generate_image(prompt.output, output_path)
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
        specs: list[ArticleImageSpec] = [
            ArticleImageSpec(
                image_key="cover",
                label="头图",
                prompt_hint=f"{content.title}\n{content.lead}\n目标气质：高质感、适合小红书长文封面",
                source_refs=[content.primary_source_ref] if content.primary_source_ref else [],
            )
        ]
        for section in content.sections:
            for block in section.blocks:
                if block.image_key:
                    specs.append(
                        ArticleImageSpec(
                            image_key=block.image_key,
                            label=section.heading,
                            prompt_hint=f"{section.heading}\n{section.summary}\n关键来源: {', '.join(section.source_refs[:3])}",
                            source_refs=section.source_refs,
                        )
                    )
                    break
        deduped: dict[str, ArticleImageSpec] = {spec.image_key: spec for spec in specs}
        return list(deduped.values())
