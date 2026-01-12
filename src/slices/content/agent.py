"""
内容创作 Agent - ML 模型风格
基于研究数据生成小红书内容

使用方式：
    agent = ContentAgent()
    result = await agent.forward(research, topic)

内置 Reflexion 循环：生成 → 审核 → 修订 → 循环直到通过
"""
from dataclasses import dataclass, field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart, ModelMessage
from ...models.schemas import ResearchResult, XHSContent, ReviewResult
from ...utils.minimax_provider import get_minimax_model
from ...utils.retry_handler import with_retry
from ...utils.logger import get_logger
from ...config.settings import RetryConfig, ReviewConfig
from .prompts import (
    content_system_prompt,
    content_user_prompt,
    content_review_system_prompt,
    content_review_user_prompt,
)

logger = get_logger(__name__)


# ============================================================================
# State 数据类
# ============================================================================

@dataclass
class ContentState:
    """内容创作运行时状态"""
    research: ResearchResult
    topic: str

    # 消息历史
    message_history: list[ModelMessage] = field(default_factory=list)

    # 当前结果
    current_content: XHSContent | None = None
    current_review: ReviewResult | None = None


# ============================================================================
# ContentAgent
# ============================================================================

class ContentAgent:
    """
    小红书内容创作 Agent（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口
    - _step: 单次生成迭代
    - _review: 审核逻辑

    使用方式：
        agent = ContentAgent()
        result = await agent.forward(research, topic)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self, max_iterations: int = None):
        """初始化内容 Agent"""
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS
        self._init_generator()
        self._init_reviewer()

    def _init_generator(self):
        """初始化生成 Agent"""
        model = get_minimax_model()
        self.generator = Agent(
            model=model,
            output_type=XHSContent,
            instrument=True,
            system_prompt=(content_system_prompt(),),
        )

    def _init_reviewer(self):
        """初始化审核 Agent"""
        self.reviewer = Agent(
            model=get_minimax_model(),
            output_type=ReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(content_review_system_prompt(),),
        )

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def forward(
        self,
        research: ResearchResult,
        topic: str
    ) -> XHSContent:
        """
        创作小红书内容（主入口）

        类似 PyTorch 的 forward 方法，带 Reflexion 循环。

        Args:
            research: 研究结果
            topic: 主题

        Returns:
            XHSContent: 创作的内容（已通过审核或达到最大迭代次数）
        """
        # 初始化状态
        state = self._init_state(research, topic)

        for iteration in range(self.max_iterations):
            # Step: 生成或修订
            await self._step(state, iteration)

            # Review: 审核
            await self._review(state)

            # 通过则返回
            if state.current_review.passed:
                self._log_success(state, iteration)
                return state.current_content

            # 未通过，更新状态继续
            self._update_state_on_failure(state, iteration)

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前结果")
        return state.current_content

    # ========================================================================
    # 核心执行方法
    # ========================================================================

    def _init_state(self, research: ResearchResult, topic: str) -> ContentState:
        """初始化内容创作状态"""
        return ContentState(research=research, topic=topic)

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

        # 执行生成
        run_result = await self.generator.run(prompt, message_history=state.message_history)
        state.current_content = run_result.output
        state.message_history.extend(run_result.new_messages())

    async def _review(self, state: ContentState) -> None:
        """审核内容"""
        logger.info("审核内容...")
        review_prompt = content_review_user_prompt(
            content=state.current_content.model_dump_json(indent=2),
            research=state.research.model_dump_json(indent=2),
        )
        review_result = await self.reviewer.run(review_prompt)
        state.current_review = review_result.output

    # ========================================================================
    # 状态更新方法
    # ========================================================================

    def _update_state_on_failure(self, state: ContentState, iteration: int) -> None:
        """审核失败时更新状态"""
        review = state.current_review

        logger.warning(f"内容审核未通过 (第{iteration+1}轮): {review.summary}")
        for issue in review.issues:
            logger.warning(f"  - [{issue.severity}] {issue.description}")

        # 构建反馈消息
        feedback_message = (
            f"内容审核未通过，请修订。\n\n"
            f"**审核反馈**：{review.summary}\n\n"
            f"**具体问题**：\n"
        )
        for issue in review.issues:
            feedback_message += f"- [{issue.severity}] {issue.description}: {issue.suggestion}\n"

        feedback_message += (
            f"\n**研究数据参考**：\n"
            f"- 可用关键信息: {len(state.research.key_infos)} 个\n"
            f"- 可用案例: {len(state.research.cases)} 个\n"
        )

        state.message_history.append(ModelRequest(parts=[
            UserPromptPart(feedback_message)
        ]))

    # ========================================================================
    # 日志方法
    # ========================================================================

    def _log_success(self, state: ContentState, iteration: int) -> None:
        """记录成功日志"""
        logger.info(f"内容审核通过 (第{iteration+1}轮)")
        logger.info(f"  - 标题: {state.current_content.title}")
        logger.info(f"  - 评分: {state.current_review.score:.1f}/100")
