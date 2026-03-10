"""研究验证器"""
from typing import List, Optional
from pydantic_ai import Agent

from .....core.base_validator import InternalValidator, InternalValidationResult
from ..schemas import ResearchResult, ReviewResult
from .....config.settings import RetryConfig
from .....utils.review_provider import get_review_model
from .....utils.logger import get_logger
from .prompts import research_review_system_prompt, research_review_user_prompt

logger = get_logger(__name__)


class ResearchDepthValidator(InternalValidator):
    """研究深度验证器 - 验证内容数量是否达标"""

    def __init__(self, min_posts: int = 3):
        self.min_posts = min_posts

    @property
    def validator_name(self) -> str:
        return "ResearchDepth"

    async def validate(self, result: ResearchResult, context: dict) -> InternalValidationResult:
        issues = []
        score = 100.0

        tracked_count = context.get("tracked_post_count", 0)
        tracked_urls: List[str] = context.get("tracked_urls", [])
        reported_count = result.sources_count

        if tracked_count < self.min_posts:
            issues.append(f"内容数量不足：已访问 {tracked_count} 个详情页，需要至少 {self.min_posts} 个")
            score -= (self.min_posts - tracked_count) * 2

        if reported_count > tracked_count * 1.5:
            issues.append(f"数据异常：Agent 自报 {reported_count} 个来源，但追踪仅记录 {tracked_count} 个详情页访问")
            score -= 10

        passed = tracked_count >= self.min_posts
        score = max(0, score)

        if passed:
            feedback = ""
        else:
            feedback = (
                f"**研究深度验证未通过**\n\n"
                f"**当前状态**：\n"
                f"- 已访问内容详情页: {tracked_count} / {self.min_posts} (最低要求)\n"
                f"- 还需访问: {max(0, self.min_posts - tracked_count)} 个\n\n"
                f"**问题**：\n"
            )
            for issue in issues:
                feedback += f"- {issue}\n"
            feedback += (
                f"\n**建议**：\n"
                f"请使用 playwright_navigate 进入更多内容详情页（URL 包含 /explore/），"
                f"深度研究其内容和评论区。"
            )
            if tracked_urls:
                feedback += f"\n\n**已访问的内容详情页**（最近 5 个）：\n"
                for url in tracked_urls[-5:]:
                    feedback += f"- {url[:60]}...\n"

        validation_result = InternalValidationResult(passed=passed, feedback=feedback, score=score)
        self._log_result(validation_result)
        return validation_result


class ResearchReviewValidator(InternalValidator):
    """研究审核验证器 - 验证数据质量"""

    def __init__(self, min_posts: int = 3):
        self.min_posts = min_posts
        self._reviewer: Optional[Agent] = None

    @property
    def validator_name(self) -> str:
        return "ResearchReview"

    @property
    def reviewer(self) -> Agent:
        if self._reviewer is None:
            self._reviewer = Agent(
                model=get_review_model(),
                output_type=ReviewResult,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,
                system_prompt=(research_review_system_prompt(),),
            )
        return self._reviewer

    async def validate(self, result: ResearchResult, context: dict) -> InternalValidationResult:
        topic = context.get("topic", "")
        target_audience = context.get("target_audience", "")

        review_prompt = research_review_user_prompt(
            topic=topic,
            target_audience=target_audience,
            research=result.model_dump_json(indent=2),
            min_posts=self.min_posts,
        )
        review_result = await self.reviewer.run(review_prompt)
        review = review_result.output

        if review.passed:
            validation_result = InternalValidationResult(passed=True, feedback="", score=review.score)
        else:
            feedback = (
                f"**数据质量审核未通过**\n\n"
                f"**审核评分**：{review.score:.1f}/100\n\n"
                f"**当前数据状态**：\n"
                f"- 内容项数量: {len(result.items)} 个\n"
                f"- 来源数量: {len(result.sources)} 个\n\n"
                f"**审核反馈**：{review.summary}\n\n"
                f"**具体问题**：\n"
            )
            for issue in review.issues:
                feedback += f"- [{issue.severity}] {issue.description}: {issue.suggestion}\n"
            validation_result = InternalValidationResult(passed=False, feedback=feedback, score=review.score)

        self._log_result(validation_result)
        return validation_result

    def _log_result(self, validation_result: InternalValidationResult) -> None:
        if validation_result.passed:
            logger.info(f"[{self.validator_name}] 数据质量验证通过")
            logger.info(f"  - 评分: {validation_result.score:.1f}/100")
        else:
            logger.warning(f"[{self.validator_name}] 数据质量验证未通过")
            logger.warning(f"  - 评分: {validation_result.score:.1f}/100")
