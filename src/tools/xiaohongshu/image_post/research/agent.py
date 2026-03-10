"""
研究 Agent - ML 模型风格
使用 Playwright MCP Server 搜索和分析小红书内容

使用方式：
    agent = ResearchAgent()
    result = await agent.forward(topic, target_audience, output_dir)

核心循环：
    for iteration in range(max_iterations):
        await step(state)      # 执行研究（每轮全新 prompt）
        passed = validate(state)  # 验证
        if passed: return       # 通过 → 返回
        build_continuation()   # 失败 → 构建续研 prompt 继续
"""
import logfire
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio

from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import ResearchResult
from .....utils.minimax_provider import get_minimax_model
from .....utils.navigate_tracker import NavigateTracker
from .....utils.logger import get_logger
from .....config.settings import RetryConfig, ResearchConfig, PathConfig, TimeoutConfig
from ..login import LoginAgent

from .validator import ResearchDepthValidator, ResearchReviewValidator
from .tools import ImageReaderAgent, WebSearchAgent
from .prompts import research_system_prompt, research_user_prompt, research_continuation_prompt
from .state import (
    ResearchState,
    build_progress_snapshot,
    combine_feedback,
)
from .utils import save_iteration_result, merge_results

logger = get_logger(__name__)


class ResearchAgent(BaseAgent):
    """小红书研究 Agent"""

    role = "小红书研究员"
    goal = "深度研究话题，收集爆款内容模式和用户偏好"

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化研究 Agent"""
        self.init_mcp_server()
        super().__init__()
        self.init_validators()

    def init_mcp_server(self) -> None:
        """初始化 Playwright MCP Server"""
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_SHARED
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )
        self.navigate_tracker = NavigateTracker(self.mcp_server)

    def init_tools(self) -> None:
        """初始化工具集"""
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)
        self.image_reader_agent = ImageReaderAgent()
        self.web_search_agent = WebSearchAgent()

    def init_agent(self) -> None:
        """初始化研究生成 Agent"""
        model = get_minimax_model()

        function_tools = [
            self.login_agent.get_tool(),
            self.image_reader_agent.get_tool(),
        ]

        self.generator = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.navigate_tracker],
            tools=function_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(research_system_prompt(),),
        )

    def init_validators(self) -> None:
        """初始化验证器"""
        self.depth_validator = ResearchDepthValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )
        self.review_validator = ResearchReviewValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )
        self.max_iterations = ResearchConfig.VALIDATION_MAX_RETRIES

    # ========================================================================
    # 核心循环：forward
    # ========================================================================

    async def forward(
        self,
        topic: str,
        target_audience: str,
        output_dir: Path | None = None
    ) -> ResearchResult:
        """
        执行研究任务（主入口）

        核心循环一目了然：
        1. step() 执行研究（每轮全新 prompt）
        2. validate() 验证结果
        3. 通过 → 返回
        4. 失败 → 构建续研 prompt 继续

        Args:
            topic: 研究主题
            target_audience: 目标受众
            output_dir: 输出目录

        Returns:
            ResearchResult: 研究结果
        """
        # 初始化状态
        state = self.create_state(topic, target_audience, output_dir)

        logger.info(f"开始研究：{topic}")
        logger.info(f"目标受众：{target_audience}")
        logger.info(f"最大迭代次数：{self.max_iterations}")

        with logfire.span(
            'research:workflow',
            topic=topic,
            target_audience=target_audience,
            max_iterations=self.max_iterations
        ) as span:

            async with self.mcp_server:
                for iteration in range(self.max_iterations):
                    with logfire.span('research:iteration', iteration=iteration + 1):
                        # Step: 执行研究
                        await self.step(state, iteration)

                        # Validate: 验证结果
                        validation = await self.validate(state.current_result)

                        if validation.passed:
                            self.log_success(span, state, iteration)
                            return self.finalize(state, iteration + 1)

                        # Feedback: 注入反馈继续
                        self.on_validation_failed(state, iteration, validation.feedback)

                # 达到最大迭代次数
                self.log_max_iterations(span, topic)
                return self.finalize(state, self.max_iterations)

    # ========================================================================
    # 工作流子步骤
    # ========================================================================

    def create_state(
        self,
        topic: str,
        target_audience: str,
        output_dir: Path | None
    ) -> ResearchState:
        """初始化研究状态"""
        self.navigate_tracker.reset(force=True)
        return ResearchState(
            topic=topic,
            target_audience=target_audience,
            output_dir=output_dir
        )

    async def step(self, state: ResearchState, iteration: int) -> None:
        """单次研究迭代（每轮全新 prompt，不携带历史消息）"""
        logger.info("=" * 50)
        logger.info(f"第 {iteration + 1}/{self.max_iterations} 轮研究")
        logger.info("=" * 50)

        # 构建提示词：首轮用完整研究提示，后续轮次用续研提示
        if iteration == 0:
            prompt = research_user_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                min_posts=ResearchConfig.MIN_POSTS_RESEARCHED,
            )
        else:
            prompt = state.continuation_prompt

        # 每轮都用全新 prompt 启动，丢弃历史对话以节省上下文
        result = await self.generator.run(prompt)

        # 更新状态
        state.current_result = result.output
        state.tracked_stats = self.navigate_tracker.get_stats()

        # 保存 state 供 validate 使用
        self._current_state = state

        self.log_step_result(state)

    # ========================================================================
    # 验证方法
    # ========================================================================

    async def validate(self, output: Any) -> ValidationResult:
        """
        验证研究结果

        Args:
            output: ResearchResult 实例

        Returns:
            ValidationResult: 验证结果
        """
        # 从实例属性获取 state context
        state = self._current_state
        tracked_stats = state.tracked_stats

        # 基础验证
        if not isinstance(output, ResearchResult):
            return ValidationResult.failure("结果类型错误")

        if not output.items or len(output.items) == 0:
            logger.warning("研究结果没有内容项")
            return ValidationResult.failure("研究结果没有内容项")

        if output.sources_count < ResearchConfig.MIN_POSTS_RESEARCHED:
            logger.warning(
                "来源数量不足: %d < %d",
                output.sources_count,
                ResearchConfig.MIN_POSTS_RESEARCHED
            )

        validation_context = {
            "topic": state.topic,
            "target_audience": state.target_audience,
            "tracked_post_count": tracked_stats["post_detail_count"],
            "tracked_urls": tracked_stats["post_detail_urls"],
        }

        # 深度验证
        logger.info("验证研究深度...")
        with logfire.span('research:validate_depth'):
            depth_result = await self.depth_validator.validate(output, validation_context)

        # 质量验证
        logger.info("验证数据质量...")
        with logfire.span('research:validate_quality'):
            review_result = await self.review_validator.validate(output, validation_context)

        passed = depth_result.passed and review_result.passed
        feedback = combine_feedback(depth_result, review_result) if not passed else ""

        if passed:
            return ValidationResult.success("研究验证通过")
        else:
            return ValidationResult.failure(feedback)

    def finalize(self, state: ResearchState, iteration: int) -> ResearchResult:
        """最终化结果：保存并合并所有迭代数据"""
        result = state.current_result

        # 保存当前轮次
        saved_file = save_iteration_result(
            result, state.topic, iteration,
            state.tracked_stats, state.output_dir, state.saved_files
        )
        logger.info(f"本轮数据已保存至: {saved_file}")

        # 如果没有历史，直接返回
        if not state.iteration_results:
            return result

        # 合并所有历史 + 当前
        return merge_results(state.iteration_results + [result], state.tracked_stats)

    def on_validation_failed(
        self,
        state: ResearchState,
        iteration: int,
        feedback: str
    ) -> None:
        """验证失败时的处理：构建下一轮的续研提示词"""
        logger.warning("验证未通过，准备下一轮研究...")

        # 保存本轮结果
        saved_file = save_iteration_result(
            state.current_result, state.topic, iteration + 1,
            state.tracked_stats, state.output_dir, state.saved_files
        )
        state.iteration_results.append(state.current_result)
        logger.info(f"本轮数据已保存至: {saved_file}")

        # 构建进度快照
        snapshot = build_progress_snapshot(state, saved_file)

        # 构建下一轮续研提示词（全新 prompt，不注入到历史消息）
        state.continuation_prompt = research_continuation_prompt(
            round_number=iteration + 2,
            progress_snapshot=snapshot,
            validation_feedback=feedback,
            topic=state.topic,
            target_audience=state.target_audience,
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED,
        )

    # ========================================================================
    # 日志方法
    # ========================================================================

    def log_step_result(self, state: ResearchState) -> None:
        """记录单步结果"""
        result = state.current_result
        tracked_count = state.tracked_stats["post_detail_count"]

        logger.info("本轮研究结果：")
        logger.info(f"  - 帖子数量（追踪）: {tracked_count}")
        logger.info(f"  - 内容来源数量: {result.sources_count}")
        logger.info(f"  - 内容项数量: {len(result.items)}")

    def log_success(self, span, state: ResearchState, iteration: int) -> None:
        """记录成功日志"""
        logger.info("研究验证全部通过！")

        span.set_attribute('final_iteration', iteration + 1)
        span.set_attribute('success', True)

        logfire.info(
            'Research completed successfully',
            topic=state.topic,
            iterations=iteration + 1,
        )

    def log_max_iterations(self, span, topic: str) -> None:
        """记录达到最大迭代次数"""
        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前结果")

        span.set_attribute('final_iteration', self.max_iterations)
        span.set_attribute('success', False)
        span.set_attribute('reason', 'max_iterations_reached')

        logfire.warn(
            'Research reached max iterations',
            topic=topic,
            max_iterations=self.max_iterations
        )
