"""
研究深度验证器
验证研究是否达到足够的深度（帖子数量）

验证项目：
- posts_researched >= min_posts（最少研究帖子数）
- post_sources 列表完整（每个帖子有 URL、标题等信息）

使用方式：
    validator = ResearchDepthValidator(min_posts=3)
    result = await validator.validate(research_result, context)
    if not result.passed:
        # 使用 result.feedback 继续探索
"""
from .internal_base import InternalValidator, InternalValidationResult
from ..models.schemas import ResearchResult


class ResearchDepthValidator(InternalValidator):
    """
    研究深度验证器 - 验证帖子数量是否达标

    验证项目：
    - posts_researched >= min_posts
    - post_sources 列表是否包含每个帖子的详细信息
    """

    def __init__(self, min_posts: int = 3):
        """
        初始化验证器

        Args:
            min_posts: 最少研究帖子数
        """
        self.min_posts = min_posts

    @property
    def validator_name(self) -> str:
        return "ResearchDepth"

    async def validate(
        self,
        result: ResearchResult,
        context: dict
    ) -> InternalValidationResult:
        """
        验证研究深度

        检查：
        1. posts_researched 是否 >= min_posts
        2. post_sources 是否包含帖子信息

        Args:
            result: ResearchResult 对象
            context: 上下文信息（未使用）

        Returns:
            InternalValidationResult: 验证结果
        """
        issues = []
        score = 100.0

        # 检查帖子数量
        posts_count = result.posts_researched
        if posts_count < self.min_posts:
            issues.append(
                f"帖子数量不足：当前 {posts_count} 个，需要至少 {self.min_posts} 个"
            )
            # 按比例扣分
            score -= (self.min_posts - posts_count) * 20

        # 检查 post_sources 完整性
        sources_count = len(result.post_sources)
        if sources_count < posts_count:
            issues.append(
                f"帖子来源信息不完整：声称研究 {posts_count} 个帖子，"
                f"但 post_sources 只有 {sources_count} 条记录"
            )
            score -= 10

        # 检查每个来源是否有必要字段
        for i, source in enumerate(result.post_sources):
            if not source.get('url'):
                issues.append(f"第 {i+1} 个帖子来源缺少 URL")
                score -= 5
            if not source.get('title'):
                issues.append(f"第 {i+1} 个帖子来源缺少标题")
                score -= 5

        # 构建结果
        passed = len(issues) == 0
        score = max(0, score)

        if passed:
            feedback = ""
        else:
            feedback = self._build_feedback(result, issues)

        validation_result = InternalValidationResult(
            passed=passed,
            feedback=feedback,
            score=score
        )

        # 记录日志
        self._log_result(validation_result)

        return validation_result

    def _build_feedback(self, result: ResearchResult, issues: list) -> str:
        """构建反馈信息"""
        feedback = (
            f"**研究深度验证未通过**\n\n"
            f"**当前状态**：\n"
            f"- 研究帖子数: {result.posts_researched} / {self.min_posts} (最低要求)\n"
            f"- 帖子来源记录: {len(result.post_sources)} 条\n\n"
            f"**问题**：\n"
        )
        for issue in issues:
            feedback += f"- {issue}\n"

        feedback += (
            f"\n**建议**：\n"
            f"请进入更多高热帖子（点赞 > 500、评论 > 100），"
            f"深度研究其内容和评论区，并记录帖子信息到 post_sources。"
        )

        return feedback
