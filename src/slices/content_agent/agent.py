"""
内容创作 Agent - ML 模型风格
基于研究数据生成小红书内容

使用方式：
    agent = ContentAgent()
    result = await agent.forward(research, topic)

核心循环：
    for iteration in range(max_iterations):
        await _step(state)      # 生成或修订
        await _review(state)    # 审核
        if passed: return       # 通过 → 返回
        state.inject_feedback() # 失败 → 注入反馈继续
"""
from pydantic_ai import Agent

from ...models.schemas import ResearchResult, XHSContent, ReviewResult
from ...utils.anthropic_provider import get_anthropic_model
from ...utils.logger import get_logger
from ...config.settings import RetryConfig, ReviewConfig

from .prompts import (
    content_system_prompt,
    content_user_prompt,
    content_review_system_prompt,
    content_review_user_prompt,
)

# 从拆分的模块导入
from ._state import ContentState, simplify_content_history
from ._feedback import build_review_feedback

logger = get_logger(__name__)


class ContentAgent:
    """
    小红书内容创作 Agent（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口（核心循环）
    - _step: 单次生成迭代
    - _review: 审核逻辑

    使用方式：
        agent = ContentAgent()
        result = await agent.forward(research, topic)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    # 历史轮数限制
    MAX_HISTORY_ROUNDS = 3

    def __init__(self, max_iterations: int = None):
        """初始化内容 Agent"""
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS
        self._init_generator()
        self._init_reviewer()

    def _init_generator(self):
        """初始化生成 Agent"""
        model = get_anthropic_model()
        self.generator = Agent(
            model=model,
            output_type=XHSContent,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,           # 用内置重试
            history_processors=[simplify_content_history],  # 用内置机制
            system_prompt=(content_system_prompt(),),
        )

    def _init_reviewer(self):
        """初始化审核 Agent"""
        self.reviewer = Agent(
            model=get_anthropic_model(),
            output_type=ReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(content_review_system_prompt(),),
        )

    # ========================================================================
    # 核心循环：forward
    # ========================================================================

    async def forward(
        self,
        research: ResearchResult,
        topic: str
    ) -> XHSContent:
        """
        创作小红书内容（主入口）

        核心循环一目了然：
        1. _step() 生成或修订
        2. _review() 审核
        3. 通过 → 返回
        4. 失败 → 注入反馈继续

        Args:
            research: 研究结果
            topic: 主题

        Returns:
            XHSContent: 创作的内容（已通过审核或达到最大迭代次数）
        """
        # 初始化状态
        state = ContentState(research=research, topic=topic)

        logger.info(f"开始生成内容：{topic}")
        logger.info(f"最大迭代次数：{self.max_iterations}")

        for iteration in range(self.max_iterations):
            # Step: 生成或修订
            await self._step(state, iteration)

            # Review: 审核
            await self._review(state)

            if state.current_review.passed:
                self._log_success(state, iteration)
                return state.current_content

            # Feedback: 注入反馈继续
            self._on_review_failed(state, iteration)

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前内容")
        return state.current_content

    # ========================================================================
    # 执行方法
    # ========================================================================

    async def _step(self, state: ContentState, iteration: int) -> None:
        """单次生成迭代"""
        if iteration == 0:
            prompt = content_user_prompt(
                topic=state.topic,
                research_data=state.research.model_dump_json(indent=2),
            )
            logger.info("开始创作内容...")
        else:
            prompt = "请根据反馈修订内容，确保数量一致、数据准确。"
            logger.info(f"根据反馈修订内容 (第{iteration+1}轮)...")

        # 执行生成（只传递最近 N 轮历史）
        recent_history = state.get_recent_history(self.MAX_HISTORY_ROUNDS)
        run_result = await self.generator.run(prompt, message_history=recent_history)
        state.current_content = run_result.output
        state.message_history.extend(run_result.new_messages())

    async def _review(self, state: ContentState) -> None:
        """审核内容（带历史记忆，只保留最近 N 轮）"""
        logger.info("审核内容...")
        review_prompt = content_review_user_prompt(
            content=state.current_content.model_dump_json(indent=2),
            research=state.research.model_dump_json(indent=2),
        )

        # 只传递最近 N 轮历史
        recent_review_history = state.review_history[-self.MAX_HISTORY_ROUNDS * 2:] if len(state.review_history) > self.MAX_HISTORY_ROUNDS * 2 else state.review_history

        review_result = await self.reviewer.run(
            review_prompt,
            message_history=recent_review_history
        )
        state.current_review = review_result.output
        state.review_history.extend(review_result.new_messages())

    def _on_review_failed(self, state: ContentState, iteration: int) -> None:
        """审核失败时的处理"""
        review = state.current_review

        logger.warning(f"内容审核未通过 (第{iteration+1}轮): {review.summary}")
        for issue in review.issues:
            logger.warning(f"  - [{issue.severity}] {issue.description}")

        # 构建并注入反馈
        feedback = build_review_feedback(review, state.research)
        state.inject_feedback(feedback)

    # ========================================================================
    # 日志方法
    # ========================================================================

    def _log_success(self, state: ContentState, iteration: int) -> None:
        """记录成功日志"""
        logger.info(f"内容审核通过 (第{iteration+1}轮)")
        logger.info(f"  - 标题: {state.current_content.title}")
        logger.info(f"  - 评分: {state.current_review.score:.1f}/100")
