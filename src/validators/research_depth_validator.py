"""
研究深度验证器
验证研究是否达到足够的深度（帖子数量）

验证基于 MCP 工具调用追踪数据（tracked_post_count），
而非 Agent 自报的 posts_researched。

验证项目：
- tracked_post_count >= min_posts（通过 playwright_navigate 追踪）
- 追踪的 URL 是否包含 /explore/ 路径（帖子详情页特征）

使用方式：
    validator = ResearchDepthValidator(min_posts=3)
    result = await validator.validate(research_result, context)
    # context 必须包含 tracked_post_count（来自 NavigateTracker）
    if not result.passed:
        # 使用 result.feedback 继续探索
"""
from typing import List
from .internal_base import InternalValidator, InternalValidationResult
from ..models.schemas import ResearchResult


class ResearchDepthValidator(InternalValidator):
    """
    研究深度验证器 - 验证帖子数量是否达标

    基于 MCP 工具调用追踪数据验证：
    - tracked_post_count >= min_posts（真实导航数据）
    - 对比 Agent 自报数据（posts_researched）检测差异
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

        基于 MCP 工具调用追踪数据验证：
        1. tracked_post_count 是否 >= min_posts（真实数据）
        2. 对比自报数据检测异常

        Args:
            result: ResearchResult 对象
            context: 上下文信息，必须包含：
                - tracked_post_count: 追踪的帖子详情页访问次数
                - tracked_urls: 追踪的帖子详情页 URL 列表

        Returns:
            InternalValidationResult: 验证结果
        """
        issues = []
        score = 100.0

        # 获取追踪数据（真实数据）
        tracked_count = context.get("tracked_post_count", 0)
        tracked_urls: List[str] = context.get("tracked_urls", [])

        # Agent 自报数据（用于对比）
        reported_count = result.posts_researched

        # 1. 检查追踪的帖子数量（主要验证依据）
        if tracked_count < self.min_posts:
            issues.append(
                f"帖子数量不足：已访问 {tracked_count} 个详情页，需要至少 {self.min_posts} 个"
            )
            # 按比例扣分
            score -= (self.min_posts - tracked_count) * 2

        # 2. 检测自报数据与追踪数据的差异（信任验证）
        if reported_count > tracked_count * 1.5:  # 自报超出追踪的 50%
            issues.append(
                f"数据异常：Agent 自报 {reported_count} 个帖子，"
                f"但追踪仅记录 {tracked_count} 个详情页访问"
            )
            score -= 10

        # 构建结果
        passed = tracked_count >= self.min_posts
        score = max(0, score)

        if passed:
            feedback = ""
        else:
            feedback = self._build_feedback(tracked_count, tracked_urls, issues)

        validation_result = InternalValidationResult(
            passed=passed,
            feedback=feedback,
            score=score
        )

        # 记录日志
        self._log_result(validation_result)

        return validation_result

    def _build_feedback(
        self,
        tracked_count: int,
        tracked_urls: List[str],
        issues: list
    ) -> str:
        """
        构建反馈信息

        Args:
            tracked_count: 追踪的帖子数量
            tracked_urls: 追踪的帖子 URL 列表
            issues: 问题列表

        Returns:
            反馈字符串
        """
        feedback = (
            f"**研究深度验证未通过**\n\n"
            f"**当前状态**：\n"
            f"- 已访问帖子详情页: {tracked_count} / {self.min_posts} (最低要求)\n"
            f"- 还需访问: {max(0, self.min_posts - tracked_count)} 个帖子\n\n"
            f"**问题**：\n"
        )
        for issue in issues:
            feedback += f"- {issue}\n"

        feedback += (
            f"\n**建议**：\n"
            f"请使用 playwright_navigate 进入更多帖子详情页（URL 包含 /explore/），"
            f"深度研究其内容和评论区。每进入一个帖子详情页，系统会自动追踪。"
        )

        # 显示已访问的帖子（最多 5 个）
        if tracked_urls:
            feedback += f"\n\n**已访问的帖子详情页**（最近 5 个）：\n"
            for url in tracked_urls[-5:]:
                feedback += f"- {url[:60]}...\n"

        return feedback
