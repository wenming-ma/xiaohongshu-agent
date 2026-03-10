"""
内容创作 Agent - ML 模型风格
基于研究数据生成小红书内容

使用方式：
    agent = ContentAgent()
    result = await agent.forward(research, topic)

核心循环：
    for iteration in range(max_iterations):
        await step(state)      # 生成或修订
        await review(state)    # 审核
        if passed: return       # 通过 → 返回
        state.inject_feedback() # 失败 → 注入反馈继续
"""
from typing import Any

from pydantic_ai import Agent

from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import ResearchResult, XHSContent, ReviewResult
from .....utils.minimax_provider import get_minimax_model
from .....utils.logger import get_logger
from .....config.settings import RetryConfig, ReviewConfig

from .prompts import (
    content_system_prompt,
    content_user_prompt,
    content_review_system_prompt,
    content_review_user_prompt,
)
from .state import ContentState, simplify_content_history
from .utils import build_review_feedback

logger = get_logger(__name__)


class ContentAgent(BaseAgent):
    """小红书内容创作 Agent"""

    role = "内容创作者"
    goal = "基于研究数据创作高质量小红书图文内容"

    MAX_HISTORY_ROUNDS = 3

    def __init__(self, max_iterations: int = None):
        """初始化内容 Agent"""
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS
        super().__init__()

    def init_tools(self) -> None:
        """初始化工具集（内容Agent不需要额外工具）"""
        pass

    def init_agent(self) -> None:
        """初始化生成和审核 Agent"""
        self.init_generator()
        self.init_reviewer()

    def init_generator(self) -> None:
        """初始化生成 Agent"""
        model = get_minimax_model()
        self.generator = Agent(
            model=model,
            output_type=XHSContent,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,           # 用内置重试
            history_processors=[simplify_content_history],  # 用内置机制
            system_prompt=(content_system_prompt(),),
        )

    def init_reviewer(self) -> None:
        """初始化审核 Agent"""
        self.reviewer = Agent(
            model=get_minimax_model(),
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
        1. step() 生成或修订
        2. review() 审核
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
            await self.step(state, iteration)

            # Validate: 验证（包含 AI 审核）
            validation = await self.validate(state.current_content)

            if validation.passed:
                self.log_success(state, iteration)
                return state.current_content

            # Feedback: 注入反馈继续
            self.on_validation_failed(state, iteration, validation.feedback)

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前内容")
        return state.current_content

    # ========================================================================
    # 工作流子步骤
    # ========================================================================

    async def step(self, state: ContentState, iteration: int) -> None:
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

        # 保存 state 供 validate 使用
        self._current_state = state

    # ========================================================================
    # 验证方法
    # ========================================================================

    async def validate(self, output: Any) -> ValidationResult:
        """
        验证内容输出（包含 AI 审核）

        Args:
            output: XHSContent 实例

        Returns:
            ValidationResult: 验证结果
        """
        if not isinstance(output, XHSContent):
            return ValidationResult.failure("输出类型错误，期望 XHSContent")

        # 基础验证
        if not output.title or not output.body:
            logger.warning("内容缺少标题或正文")
            return ValidationResult.failure("内容缺少标题或正文")

        if len(output.title) > 20:
            logger.warning("标题过长: %d 字符", len(output.title))
            return ValidationResult.failure(f"标题过长: {len(output.title)} 字符")

        # AI 审核
        state = self._current_state
        logger.info("审核内容...")
        review_prompt = content_review_user_prompt(
            content=output.model_dump_json(indent=2),
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

        if state.current_review.passed:
            return ValidationResult.success(f"审核通过，评分: {state.current_review.score:.1f}/100")
        else:
            feedback = build_review_feedback(state.current_review, state.research)
            return ValidationResult.failure(feedback)

    # ========================================================================
    # 审核方法
    # ========================================================================

    def on_validation_failed(self, state: ContentState, iteration: int, feedback: str) -> None:
        """验证失败时的处理"""
        review = state.current_review

        if review is None:
            # 基础验证失败（如标题过长），未执行 AI 审核
            logger.warning(f"内容验证未通过 (第{iteration+1}轮): {feedback}")
        else:
            logger.warning(f"内容审核未通过 (第{iteration+1}轮): {review.summary}")
            for issue in review.issues:
                logger.warning(f"  - [{issue.severity}] {issue.description}")

        # 注入反馈
        state.inject_feedback(feedback)

    # ========================================================================
    # 日志方法
    # ========================================================================

    def log_success(self, state: ContentState, iteration: int) -> None:
        """记录成功日志"""
        logger.info(f"内容审核通过 (第{iteration+1}轮)")
        logger.info(f"  - 标题: {state.current_content.title}")
        logger.info(f"  - 评分: {state.current_review.score:.1f}/100")
