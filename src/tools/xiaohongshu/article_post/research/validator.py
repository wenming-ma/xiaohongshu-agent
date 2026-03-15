"""Validators for long-form article research."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent

from .....config.settings import ReviewConfig, RetryConfig
from .....core.base_validator import InternalValidationResult, InternalValidator
from .....utils.logger import get_logger
from .....utils.providers import get_text_model
from ..schemas import (
    ArticleResearchResult,
    ArticleResearchReviewIssue,
    ArticleResearchReviewResult,
    ArticleStrategy,
    ResearchDimensionReviewResult,
    ResearchReviewDimension,
)
from .prompts import (
    downstream_usability_review_system_prompt,
    research_review_user_prompt,
    source_quality_review_system_prompt,
    strategy_fit_review_system_prompt,
    timeliness_risk_review_system_prompt,
    traceability_review_system_prompt,
)
from .tools import LocalEvidenceStore

logger = get_logger(__name__)

_DIMENSION_LABELS: dict[ResearchReviewDimension, str] = {
    ResearchReviewDimension.TRACEABILITY: "证据可追溯性",
    ResearchReviewDimension.SOURCE_QUALITY: "来源质量",
    ResearchReviewDimension.STRATEGY_FIT: "策略匹配性",
    ResearchReviewDimension.TIMELINESS_RISK: "时效性与风险",
    ResearchReviewDimension.DOWNSTREAM_USABILITY: "下游可用性",
}

_SEVERITY_MARKERS: dict[str, str] = {
    "critical": "!!!",
    "warning": "!!",
    "info": "i",
}

_DIMENSION_CONFIG: list[tuple[ResearchReviewDimension, Callable[[], str], bool]] = [
    (ResearchReviewDimension.TRACEABILITY, traceability_review_system_prompt, True),
    (ResearchReviewDimension.SOURCE_QUALITY, source_quality_review_system_prompt, True),
    (ResearchReviewDimension.STRATEGY_FIT, strategy_fit_review_system_prompt, False),
    (ResearchReviewDimension.TIMELINESS_RISK, timeliness_risk_review_system_prompt, True),
    (ResearchReviewDimension.DOWNSTREAM_USABILITY, downstream_usability_review_system_prompt, False),
]


class ResearchRulesValidator(InternalValidator):
    """Deterministic validation rules for article research."""

    @property
    def validator_name(self) -> str:
        return "ArticleResearchRules"

    async def validate(
        self,
        result: ArticleResearchResult,
        context: dict,
    ) -> InternalValidationResult:
        if not isinstance(result, ArticleResearchResult):
            validation_result = InternalValidationResult(
                passed=False,
                feedback="研究结果类型错误",
                score=0.0,
            )
            self._log_result(validation_result)
            return validation_result

        min_source_pages = int(context.get("min_source_pages", 0))
        min_unique_domains = int(context.get("min_unique_domains", 0))

        issues: list[str] = []
        if result.sources_count < min_source_pages:
            issues.append(f"研究深度不足，仅收集到 {result.sources_count} 个来源，至少需要 {min_source_pages} 个")
        if result.unique_domains_count < min_unique_domains:
            issues.append(
                f"域名覆盖不足，仅覆盖 {result.unique_domains_count} 个域名，至少需要 {min_unique_domains} 个"
            )
        if not result.claims:
            issues.append("研究结果缺少结构化 claims")
        if result.claims and not all(claim.source_refs for claim in result.claims):
            issues.append("存在没有来源映射的 claim")

        valid_source_refs = {source.source_ref for source in result.sources}
        if not all(
            ref in valid_source_refs for claim in result.claims for ref in claim.source_refs
        ):
            issues.append("存在引用无效 source_ref 的 claim")
        if result.suggested_strategy == ArticleStrategy.REPURPOSE_VIDEO and not any(
            transcript.success for transcript in result.transcripts
        ):
            issues.append("视频搬运策略缺少可用转录")

        if not issues:
            validation_result = InternalValidationResult(
                passed=True,
                feedback="",
                score=100.0,
            )
            self._log_result(validation_result)
            return validation_result

        feedback_lines = [
            "**研究规则校验未通过**",
            "",
            f"- 来源数: {result.sources_count}",
            f"- 域名数: {result.unique_domains_count}",
            f"- Claims 数: {len(result.claims)}",
            f"- 转录数: {len([item for item in result.transcripts if item.success])}",
            "",
            "**具体问题**：",
        ]
        feedback_lines.extend(f"- {issue}" for issue in issues)
        validation_result = InternalValidationResult(
            passed=False,
            feedback="\n".join(feedback_lines),
            score=max(0.0, 100.0 - (len(issues) * 25.0)),
        )
        self._log_result(validation_result)
        return validation_result


class ResearchReviewValidator(InternalValidator):
    """Multi-dimension reviewer for article research quality."""

    def __init__(self) -> None:
        self.last_review_result: ArticleResearchReviewResult | None = None
        self.last_dimension_results: list[ResearchDimensionReviewResult] = []

    @property
    def validator_name(self) -> str:
        return "ArticleResearchReview"

    def _build_reviewers(
        self,
        output_dir: Path | None = None,
    ) -> list[tuple[ResearchReviewDimension, Agent]]:
        model = get_text_model()
        evidence_tools = []
        if output_dir and (output_dir / "source_index.json").exists():
            store = LocalEvidenceStore(output_dir)
            evidence_tools = store.get_tools()
            logger.info("研究审核器已注册本地证据工具 (%d 个)", len(evidence_tools))

        reviewers: list[tuple[ResearchReviewDimension, Agent]] = []
        for dimension, system_prompt_fn, use_evidence_tools in _DIMENSION_CONFIG:
            reviewers.append(
                (
                    dimension,
                    Agent(
                        model=model,
                        output_type=ResearchDimensionReviewResult,
                        instrument=True,
                        retries=RetryConfig.AGENT_RETRIES,
                        system_prompt=(system_prompt_fn(),),
                        tools=evidence_tools if use_evidence_tools else [],
                    ),
                )
            )
        return reviewers

    async def validate(
        self,
        result: ArticleResearchResult,
        context: dict,
    ) -> InternalValidationResult:
        topic = str(context.get("topic", "")).strip()
        target_audience = str(context.get("target_audience", "")).strip()
        requested_strategy = context.get("requested_strategy", ArticleStrategy.AUTO)
        output_dir = context.get("output_dir")
        if isinstance(output_dir, str):
            output_dir = Path(output_dir)

        requested_strategy_value = (
            requested_strategy.value
            if isinstance(requested_strategy, ArticleStrategy)
            else str(requested_strategy or ArticleStrategy.AUTO.value)
        )
        research_json = result.model_dump_json(indent=2)
        stats_json = json.dumps(
            self._build_research_stats(result),
            ensure_ascii=False,
            indent=2,
        )
        reviewers = self._build_reviewers(output_dir)

        async def _run_one(
            dimension: ResearchReviewDimension,
            agent: Agent,
        ) -> ResearchDimensionReviewResult:
            run_result = await agent.run(
                research_review_user_prompt(
                    topic=topic,
                    target_audience=target_audience,
                    requested_strategy=requested_strategy_value,
                    stats_json=stats_json,
                    research_json=research_json,
                )
            )
            review = run_result.output
            review.dimension = dimension
            for issue in review.issues:
                issue.dimension = dimension
            return review

        dimension_results = await asyncio.gather(
            *(_run_one(dimension, agent) for dimension, agent in reviewers)
        )

        review = self._aggregate(list(dimension_results))
        self.last_review_result = review
        self.last_dimension_results = list(dimension_results)
        feedback = self._build_feedback(review) if not review.passed else ""
        validation_result = InternalValidationResult(
            passed=review.passed,
            feedback=feedback,
            score=review.score,
        )
        self._log_result(validation_result)
        return validation_result

    @staticmethod
    def _aggregate(
        dimension_results: list[ResearchDimensionReviewResult],
    ) -> ArticleResearchReviewResult:
        all_issues: list[ArticleResearchReviewIssue] = []
        score = 100.0
        has_critical = False

        for dimension_result in dimension_results:
            for issue in dimension_result.issues:
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
        return ArticleResearchReviewResult(
            passed=passed,
            score=score,
            issues=all_issues,
            dimension_results=dimension_results,
            summary="" if passed else "研究审核未通过",
        )

    @staticmethod
    def _build_feedback(review: ArticleResearchReviewResult) -> str:
        lines = [
            "**研究审核未通过**",
            "",
            f"**审核评分**：{review.score:.1f}/100",
            "",
            "**具体问题**：",
        ]
        for dimension_result in review.dimension_results:
            if not dimension_result.issues:
                continue
            label = _DIMENSION_LABELS.get(
                dimension_result.dimension,
                dimension_result.dimension.value,
            )
            lines.append(f"\n### {label}")
            if dimension_result.summary:
                lines.append(f"- 总结：{dimension_result.summary}")
            for issue in dimension_result.issues:
                marker = _SEVERITY_MARKERS.get(issue.severity, "i")
                suggestion = f"（建议：{issue.suggestion}）" if issue.suggestion else ""
                lines.append(f"- [{marker}] {issue.description}{suggestion}")
        return "\n".join(lines)

    @staticmethod
    def _build_research_stats(result: ArticleResearchResult) -> dict[str, object]:
        source_types = {
            "article": 0,
            "video": 0,
            "embedded_video": 0,
        }
        dated_sources = 0
        metadata_complete_sources = 0
        total_quality_score = 0.0

        for source in result.sources:
            source_types[source.source_type.value] = source_types.get(source.source_type.value, 0) + 1
            if source.published_at:
                dated_sources += 1
            if source.title and source.domain and source.url:
                metadata_complete_sources += 1
            total_quality_score += float(source.quality_score or 0.0)

        transcript_success_count = len([item for item in result.transcripts if item.success])
        keyword_count = len([item for item in result.keywords if str(item).strip()])
        claim_count = len(result.claims)
        sources_count = len(result.sources)

        return {
            "sources_count": sources_count,
            "unique_domains_count": result.unique_domains_count,
            "claims_count": claim_count,
            "keywords_count": keyword_count,
            "primary_source_ref": result.primary_source_ref,
            "suggested_strategy": result.suggested_strategy.value,
            "transcript_success_count": transcript_success_count,
            "dated_sources_count": dated_sources,
            "metadata_complete_sources_count": metadata_complete_sources,
            "average_quality_score": round(total_quality_score / sources_count, 1) if sources_count else 0.0,
            "source_type_counts": source_types,
        }
