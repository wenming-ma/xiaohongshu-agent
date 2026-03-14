"""长文内容多维审核验证器"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic_ai import Agent

from .....config.settings import ReviewConfig, RetryConfig
from .....core.base_validator import InternalValidator, InternalValidationResult
from .....utils.logger import get_logger
from .....utils.providers import get_text_model
from ..schemas import (
    ArticleReviewIssue,
    ArticleReviewResult,
    DimensionReviewResult,
    ReviewDimension,
    XHSArticleContent,
)
from .prompts import (
    accuracy_review_system_prompt,
    naturalness_review_system_prompt,
    readability_review_system_prompt,
    review_full_user_prompt,
    review_text_user_prompt,
    structure_review_system_prompt,
)
from .tools import EvidenceReader

logger = get_logger(__name__)

_DIMENSION_LABELS: dict[ReviewDimension, str] = {
    ReviewDimension.STRUCTURE: "结构完整性",
    ReviewDimension.ACCURACY: "事实准确性",
    ReviewDimension.READABILITY: "可读性",
    ReviewDimension.NATURALNESS: "自然度/人味",
}

_SEVERITY_MARKERS: dict[str, str] = {
    "critical": "!!!",
    "warning": "!!",
    "info": "i",
}

# Dimension config: (system_prompt_fn, input_type)
# input_type: "full" = content_json + research_json, "text" = rendered_body only
_DIMENSION_CONFIG: list[tuple[ReviewDimension, callable, str]] = [
    (ReviewDimension.STRUCTURE, structure_review_system_prompt, "full"),
    (ReviewDimension.ACCURACY, accuracy_review_system_prompt, "full"),
    (ReviewDimension.READABILITY, readability_review_system_prompt, "text"),
    (ReviewDimension.NATURALNESS, naturalness_review_system_prompt, "text"),
]


class ContentReviewValidator(InternalValidator):
    """多维内容审核验证器 — 4 个专业审核员并行运行"""

    @property
    def validator_name(self) -> str:
        return "ContentReview"

    def _build_reviewers(
        self, output_dir: Path | None = None,
    ) -> list[tuple[ReviewDimension, Agent, str]]:
        model = get_text_model()
        evidence_tools = []
        if output_dir and (output_dir / "source_index.json").exists():
            reader = EvidenceReader(output_dir)
            evidence_tools = reader.get_tools()
            logger.info("审核器已注册 EvidenceReader 工具 (%d 个)", len(evidence_tools))

        reviewers = []
        for dimension, system_prompt_fn, input_type in _DIMENSION_CONFIG:
            # Only the accuracy reviewer gets evidence tools
            tools = evidence_tools if dimension == ReviewDimension.ACCURACY else []
            reviewers.append(
                (
                    dimension,
                    Agent(
                        model=model,
                        output_type=DimensionReviewResult,
                        instrument=True,
                        retries=RetryConfig.AGENT_RETRIES,
                        system_prompt=(system_prompt_fn(),),
                        tools=tools,
                    ),
                    input_type,
                )
            )
        return reviewers

    async def validate(
        self,
        result: XHSArticleContent,
        context: dict,
    ) -> InternalValidationResult:
        content_json = result.model_dump_json(indent=2)
        research_json = context.get("research_json", "")
        rendered_body = result.rendered_body
        output_dir: Path | None = context.get("output_dir")

        # Rebuild reviewers with evidence tools when output_dir is available
        reviewers = self._build_reviewers(output_dir)

        # Run all 4 dimension reviewers in parallel
        async def _run_one(
            dimension: ReviewDimension,
            agent: Agent,
            input_type: str,
        ) -> DimensionReviewResult:
            if input_type == "full":
                prompt = review_full_user_prompt(
                    content_json=content_json,
                    research_json=research_json,
                )
            else:
                prompt = review_text_user_prompt(rendered_body=rendered_body)
            run_result = await agent.run(prompt)
            return run_result.output

        dimension_results = await asyncio.gather(
            *(_run_one(dim, agent, itype) for dim, agent, itype in reviewers)
        )

        review = self._aggregate(list(dimension_results))
        feedback = self._build_feedback(review) if not review.passed else ""

        validation_result = InternalValidationResult(
            passed=review.passed,
            feedback=feedback,
            score=review.score,
        )
        self._log_result(validation_result)
        return validation_result

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(
        dimension_results: list[DimensionReviewResult],
    ) -> ArticleReviewResult:
        all_issues: list[ArticleReviewIssue] = []
        score = 100.0
        has_critical = False

        for dr in dimension_results:
            for issue in dr.issues:
                all_issues.append(issue)
                if issue.severity == "critical":
                    score -= ReviewConfig.CRITICAL_PENALTY
                    has_critical = True
                elif issue.severity == "warning":
                    score -= ReviewConfig.WARNING_PENALTY
                else:
                    score -= ReviewConfig.INFO_PENALTY

        score = max(score, 0.0)
        passed = score >= ReviewConfig.PASS_SCORE and not has_critical

        return ArticleReviewResult(
            passed=passed,
            score=score,
            issues=all_issues,
            dimension_results=dimension_results,
            summary="" if passed else "长文审核未通过",
        )

    @staticmethod
    def _build_feedback(review: ArticleReviewResult) -> str:
        lines: list[str] = [
            f"**内容审核未通过**\n\n"
            f"**审核评分**：{review.score:.1f}/100\n\n"
            f"**具体问题**：",
        ]
        for dr in review.dimension_results:
            if not dr.issues:
                continue
            label = _DIMENSION_LABELS.get(dr.dimension, dr.dimension.value)
            lines.append(f"\n### {label}")
            for issue in dr.issues:
                marker = _SEVERITY_MARKERS.get(issue.severity, "i")
                suggestion = f"（建议：{issue.suggestion}）" if issue.suggestion else ""
                lines.append(f"- [{marker}] {issue.description}{suggestion}")
        return "\n".join(lines)
