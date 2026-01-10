"""
内容创作 Agent
基于研究数据生成小红书内容
内置 Reflexion 循环：生成 → 审核 → 修订 → 循环直到通过
"""
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from ..models.schemas import ResearchResult, XHSContent, ReviewResult
from ..utils.minimax_provider import get_minimax_model
from ..utils.retry_handler import with_retry
from ..utils.logger import get_logger
from ..config.settings import RetryConfig, ReviewConfig
from prompts import get_system_prompt, get_user_prompt

logger = get_logger(__name__)


class ContentAgent:
    """小红书内容创作 Agent（带 Reflexion 循环）"""

    def __init__(self, max_iterations: int = None):
        """
        初始化内容 Agent

        Args:
            max_iterations: 最大审核迭代次数，默认使用配置
        """
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS

        # 使用 MiniMax 模型
        model = get_minimax_model()

        # 生成 Agent
        self.generator = Agent(
            model=model,
            output_type=XHSContent,
            instrument=True,
            system_prompt=(get_system_prompt("content"),),
        )

        # 审核 Agent（文本审核统一使用 MiniMax，复用现有的 review 提示词）
        self.reviewer = Agent(
            model=get_minimax_model(),
            output_type=ReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("content_review"),),
        )

    async def _review(self, content: XHSContent, research: ResearchResult) -> ReviewResult:
        """
        审核内容

        Args:
            content: 待审核的内容
            research: 研究数据（作为审核依据）

        Returns:
            ReviewResult: 审核结果
        """
        review_prompt = get_user_prompt(
            "content_review",
            content=content.model_dump_json(indent=2),
            research=research.model_dump_json(indent=2)
        )
        review_result = await self.reviewer.run(review_prompt)
        return review_result.output

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def create_content(
        self,
        research: ResearchResult,
        topic: str
    ) -> XHSContent:
        """
        创作小红书内容（带 Reflexion 循环 + 外层重试）

        Args:
            research: 研究结果
            topic: 主题

        Returns:
            XHSContent: 创作的内容（已通过审核或达到最大迭代次数）
        """
        messages = []  # 消息历史
        content = None
        review = None

        for i in range(self.max_iterations):
            # 1. 生成或继续修订
            if i == 0:
                prompt = get_user_prompt(
                    "content",
                    topic=topic,
                    research_data=research.model_dump_json(indent=2)
                )
                logger.info("开始创作内容...")
            else:
                # 将审核反馈注入消息历史
                feedback_message = (
                    f"内容审核未通过，请修订。\n\n"
                    f"**审核反馈**：{review.summary}\n\n"
                    f"**具体问题**：\n"
                )
                for issue in review.issues:
                    feedback_message += f"- [{issue.severity}] {issue.description}: {issue.suggestion}\n"

                feedback_message += (
                    f"\n**研究数据参考**：\n"
                    f"- 可用关键信息: {len(research.key_infos)} 个\n"
                    f"- 可用案例: {len(research.cases)} 个\n"
                )

                messages.append(ModelRequest(parts=[
                    UserPromptPart(feedback_message)
                ]))
                prompt = "请根据反馈修订内容，确保数量一致、数据准确。"
                logger.info(f"根据反馈修订内容 (第{i+1}轮)...")

            # 执行生成
            run_result = await self.generator.run(prompt, message_history=messages)
            content = run_result.output
            messages.extend(run_result.new_messages())  # 保留历史

            # 2. 审核
            logger.info(f"审核内容 (第{i+1}轮)...")
            review = await self._review(content, research)

            # 3. 通过则返回
            if review.passed:
                logger.info(f"内容审核通过 (第{i+1}轮)")
                logger.info(f"  - 标题: {content.title}")
                logger.info(f"  - 评分: {review.score:.1f}/100")
                return content

            # 未通过，打印反馈
            logger.warning(f"内容审核未通过 (第{i+1}轮): {review.summary}")
            for issue in review.issues:
                logger.warning(f"  - [{issue.severity}] {issue.description}")

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前结果")
        return content
