"""内容创作工具函数"""
from ..schemas import ResearchResult, ReviewResult


def build_review_feedback(review: ReviewResult, research: ResearchResult) -> str:
    """构建审核反馈消息"""
    feedback_message = (
        f"内容审核未通过，请修订。\n\n"
        f"**审核反馈**：{review.summary}\n\n"
        f"**具体问题**：\n"
    )

    for issue in review.issues:
        feedback_message += f"- [{issue.severity}] {issue.description}: {issue.suggestion}\n"

    feedback_message += (
        f"\n**研究数据参考**：\n"
        f"- 可用内容项: {len(research.items)} 个\n"
    )

    if research.keywords:
        keywords_preview = ', '.join(research.keywords[:10])
        if len(research.keywords) > 10:
            keywords_preview += f" (共{len(research.keywords)}个)"
        feedback_message += f"- 关键词: {keywords_preview}\n"

    return feedback_message
