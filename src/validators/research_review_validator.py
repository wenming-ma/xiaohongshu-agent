"""
研究审核验证器
验证研究数据的质量（实体数量、案例数量、具体性、评论区数据等）

验证项目：
- 实体数量 >= 15
- 案例数量 >= 8
- 具体性（无"某公司"等模糊表述）
- 评论区数据占比 >= 30%

使用 AI Agent 进行审核（原有的 reviewer 逻辑）

使用方式：
    validator = ResearchReviewValidator()
    result = await validator.validate(research_result, context)
    if not result.passed:
        # 使用 result.feedback 继续探索
"""
from typing import Optional
from pydantic_ai import Agent
from .internal_base import InternalValidator, InternalValidationResult
from ..models.schemas import ResearchResult, ReviewResult
from ..config.settings import RetryConfig
from prompts import get_system_prompt, get_user_prompt


class ResearchReviewValidator(InternalValidator):
    """
    研究审核验证器 - 验证数据质量

    验证项目：
    - 实体数量 >= 15
    - 案例数量 >= 8
    - 具体性（无模糊表述）
    - 评论区数据占比 >= 30%

    使用 AI Agent 进行审核，提供详细的反馈信息。
    """

    def __init__(self, min_posts: int = 3):
        """
        初始化验证器

        Args:
            min_posts: 最少帖子数（传给审核提示词）
        """
        self.min_posts = min_posts
        self._reviewer: Optional[Agent] = None

    @property
    def validator_name(self) -> str:
        return "ResearchReview"

    @property
    def reviewer(self) -> Agent:
        """延迟初始化 reviewer Agent"""
        if self._reviewer is None:
            from ..utils.model_factory import get_model
            self._reviewer = Agent(
                model=get_model(),
                output_type=ReviewResult,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,
                system_prompt=(get_system_prompt("research_review"),),
            )
        return self._reviewer

    async def validate(
        self,
        result: ResearchResult,
        context: dict
    ) -> InternalValidationResult:
        """
        验证研究数据质量

        使用 AI Agent 审核研究结果，检查：
        - 实体数量是否充足
        - 案例数量是否充足
        - 信息是否具体（无模糊表述）
        - 评论区数据占比是否达标

        Args:
            result: ResearchResult 对象
            context: 上下文信息（需要 topic、target_audience）

        Returns:
            InternalValidationResult: 验证结果
        """
        topic = context.get("topic", "")
        target_audience = context.get("target_audience", "")

        # 调用 reviewer Agent 进行审核
        review = await self._review(result, topic, target_audience)

        if review.passed:
            validation_result = InternalValidationResult(
                passed=True,
                feedback="",
                score=review.score
            )
        else:
            feedback = self._build_feedback(review, result)
            validation_result = InternalValidationResult(
                passed=False,
                feedback=feedback,
                score=review.score
            )

        # 记录日志
        self._log_result(validation_result)

        return validation_result

    async def _review(
        self,
        result: ResearchResult,
        topic: str,
        target_audience: str
    ) -> ReviewResult:
        """
        调用 reviewer Agent 进行审核

        Args:
            result: 研究结果
            topic: 研究主题
            target_audience: 目标受众

        Returns:
            ReviewResult: 审核结果
        """
        review_prompt = get_user_prompt(
            "research_review",
            topic=topic,
            target_audience=target_audience,
            research=result.model_dump_json(indent=2),
            min_posts=self.min_posts,
        )
        review_result = await self.reviewer.run(review_prompt)
        return review_result.output

    def _build_feedback(self, review: ReviewResult, result: ResearchResult) -> str:
        """构建反馈信息"""
        feedback = (
            f"**数据质量审核未通过**\n\n"
            f"**审核评分**：{review.score:.1f}/100\n\n"
            f"**当前数据状态**：\n"
            f"- 关键信息数量: {len(result.key_infos)} 个\n"
            f"- 案例数量: {len(result.cases)} 个\n"
            f"- 评论区数据占比: {result.comment_data_ratio:.0%}\n"
            f"- 可信度: {result.credibility}\n\n"
            f"**审核反馈**：{review.summary}\n\n"
            f"**具体问题**：\n"
        )
        for issue in review.issues:
            feedback += f"- [{issue.severity}] {issue.description}: {issue.suggestion}\n"

        return feedback

    def _log_result(self, validation_result: InternalValidationResult) -> None:
        """记录验证结果（覆盖基类方法以显示评分）"""
        if validation_result.passed:
            print(f"   ✅ [{self.validator_name}] 数据质量验证通过")
            print(f"      - 评分: {validation_result.score:.1f}/100")
        else:
            print(f"   ⚠️  [{self.validator_name}] 数据质量验证未通过")
            print(f"      - 评分: {validation_result.score:.1f}/100")
