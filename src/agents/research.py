"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容

验证流程：
1. generator.run() 执行研究
2. ResearchDepthValidator 验证帖子数量（基于 MCP 工具调用追踪）
3. ResearchReviewValidator 验证数据质量
4. 两个都通过 → 返回结果
5. 任一失败 → 注入反馈，继续循环（保持消息历史）
"""
import logfire
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.messages import ModelRequest, UserPromptPart
from ..models.schemas import ResearchResult
from ..utils.model_factory import get_model
from ..utils.retry_handler import with_retry
from ..utils.navigate_tracker import NavigateTracker
from ..validators import ResearchDepthValidator, ResearchReviewValidator
from ..config.settings import RetryConfig, ResearchConfig, PathConfig, TimeoutConfig
from prompts import get_system_prompt, get_user_prompt


class ResearchAgent:
    """
    小红书研究 Agent

    研究流程：
    1. 使用 Playwright MCP 工具在小红书搜索和浏览
    2. 进入高热帖子详情页，阅读内容和评论区
    3. 提取实体、案例等数据
    4. 验证帖子数量和数据质量
    5. 未通过则继续探索，直到满足要求
    """

    def __init__(self):
        """初始化研究 Agent"""
        # 获取带 HTTP 重试的 Model（根据配置选择 Anthropic 或 OpenRouter）
        model = get_model()

        # Playwright MCP Server 实例
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp'],
            env={
                'HEADLESS': 'false',  # 显示浏览器窗口
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_XHS
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )

        # 导航追踪器 - 包装 MCP Server 以追踪帖子详情页访问
        self.navigate_tracker = NavigateTracker(self.mcp_server)

        # 研究生成 Agent（使用追踪器包装的工具集）
        self.generator = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.navigate_tracker],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("research"),),
        )

        # 初始化验证器
        self.depth_validator = ResearchDepthValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )
        self.review_validator = ResearchReviewValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )

        # 验证配置
        self.max_iterations = ResearchConfig.VALIDATION_MAX_RETRIES

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        print("\n   🔧 正在检查可用工具...")

        try:
            async with self.mcp_server as server:
                tools = await server.list_tools()
                print(f"\n   📋 发现 {len(tools)} 个 Playwright MCP 工具:")
                for tool in tools:
                    tool_name = f"{self.mcp_server.tool_prefix}_{tool.name}" if self.mcp_server.tool_prefix else tool.name
                    print(f"      ✅ {tool_name}")
                    if hasattr(tool, 'description') and tool.description:
                        print(f"         {tool.description[:80]}...")
        except Exception as e:
            print(f"   ⚠️  无法列出工具: {e}")
            print(f"   提示: 工具将在首次 Agent 调用时自动发现")

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def _run_generator(self, prompt, message_history):
        """对单次模型调用做重试，保持当前消息历史不丢失"""
        if prompt is None:
            return await self.generator.run(message_history=message_history)
        return await self.generator.run(prompt, message_history=message_history)

    async def research(self, topic: str, target_audience: str) -> ResearchResult:
        """
        执行研究任务

        验证流程（内部循环）：
        1. generator.run() 执行研究
        2. ResearchDepthValidator 验证帖子数量
        3. ResearchReviewValidator 验证数据质量
        4. 两个都通过 → 返回结果
        5. 任一失败 → 注入反馈，继续循环

        @with_retry 处理网络/API 错误（重试整个研究）
        浏览器在验证通过后才关闭。

        Args:
            topic: 研究主题
            target_audience: 目标受众

        Returns:
            ResearchResult: 研究结果（已通过验证）
        """
        # 准备初始提示词
        initial_prompt = get_user_prompt(
            "research",
            topic=topic,
            target_audience=target_audience,
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )

        # 保持消息历史
        message_history = []
        result = None

        # 重置导航追踪器（强制清空，避免自动 reset 跳过）
        self.navigate_tracker.reset(force=True)

        print(f"\n📚 开始研究：{topic}")
        print(f"   目标受众：{target_audience}")
        print(f"   最大迭代次数：{self.max_iterations}")

        # 使用 logfire span 追踪整个研究过程
        with logfire.span(
            'research:workflow',
            topic=topic,
            target_audience=target_audience,
            max_iterations=self.max_iterations
        ) as research_span:
            async with self.mcp_server:  # 浏览器保持打开
                for iteration in range(self.max_iterations):
                    print(f"\n{'='*50}")
                    print(f"🔄 第 {iteration + 1}/{self.max_iterations} 轮研究")
                    print(f"{'='*50}")

                    # 使用 logfire span 追踪每次迭代
                    with logfire.span(
                        'research:iteration',
                        iteration=iteration + 1,
                        max_iterations=self.max_iterations
                    ) as iteration_span:
                        # 1. 执行研究
                        if iteration == 0:
                            # 首轮：使用初始提示词；失败重试仅作用于本轮调用
                            agent_result = await self._run_generator(
                                initial_prompt,
                                message_history=message_history
                            )
                        else:
                            # 后续轮：继续沿用消息历史；失败重试不清空历史
                            agent_result = await self._run_generator(
                                None,
                                message_history=message_history
                            )

                        result = agent_result.output

                        # 更新消息历史
                        message_history = list(agent_result.all_messages())

                        # 获取追踪的帖子数量（真实数据）
                        tracked_stats = self.navigate_tracker.get_stats()
                        tracked_post_count = tracked_stats["post_detail_count"]

                        print(f"\n📊 本轮研究结果：")
                        print(f"   - 帖子数量（追踪）: {tracked_post_count}")
                        print(f"   - 帖子数量（自报）: {result.posts_researched}")
                        print(f"   - 关键信息数量: {len(result.key_infos)}")
                        print(f"   - 案例数量: {len(result.cases)}")
                        print(f"   - 评论区数据占比: {result.comment_data_ratio:.0%}")

                        # 记录迭代结果到 span
                        iteration_span.set_attribute('tracked_post_count', tracked_post_count)
                        iteration_span.set_attribute('reported_post_count', result.posts_researched)
                        iteration_span.set_attribute('key_infos_count', len(result.key_infos))
                        iteration_span.set_attribute('cases_count', len(result.cases))
                        iteration_span.set_attribute('comment_data_ratio', result.comment_data_ratio)

                        # 构建验证上下文（包含追踪数据）
                        validation_context = {
                            "topic": topic,
                            "target_audience": target_audience,
                            "tracked_post_count": tracked_post_count,
                            "tracked_urls": tracked_stats["post_detail_urls"],
                        }

                        # 2. 验证帖子数量（使用追踪数据）
                        print(f"\n🔍 验证研究深度...")
                        with logfire.span('research:validate_depth'):
                            depth_result = await self.depth_validator.validate(
                                result, validation_context
                            )

                        # 3. 验证数据质量
                        print(f"🔍 验证数据质量...")
                        with logfire.span('research:validate_quality'):
                            review_result = await self.review_validator.validate(
                                result, validation_context
                            )

                        # 记录验证结果
                        iteration_span.set_attribute('depth_passed', depth_result.passed)
                        iteration_span.set_attribute('depth_score', depth_result.score)
                        iteration_span.set_attribute('review_passed', review_result.passed)
                        iteration_span.set_attribute('review_score', review_result.score)

                        # 4. 两个都通过？
                        if depth_result.passed and review_result.passed:
                            print(f"\n✅ 研究验证全部通过！")
                            print(f"   - 深度验证评分: {depth_result.score:.1f}/100")
                            print(f"   - 质量验证评分: {review_result.score:.1f}/100")
                            
                            # 记录最终结果到研究 span
                            research_span.set_attribute('final_iteration', iteration + 1)
                            research_span.set_attribute('final_depth_score', depth_result.score)
                            research_span.set_attribute('final_review_score', review_result.score)
                            research_span.set_attribute('success', True)
                            
                            logfire.info(
                                'Research completed successfully',
                                topic=topic,
                                iterations=iteration + 1,
                                depth_score=depth_result.score,
                                review_score=review_result.score
                            )
                            return result

                        # 5. 构建反馈，继续循环
                        feedback = self._combine_feedback(depth_result, review_result)
                        print(f"\n⚠️  验证未通过，注入反馈继续探索...")

                        # 注入反馈到消息历史
                        feedback_message = ModelRequest(
                            parts=[UserPromptPart(content=feedback)]
                        )
                        message_history.append(feedback_message)

                # 达到最大迭代次数
                print(f"\n⚠️  达到最大迭代次数 ({self.max_iterations})，返回当前结果")
                
                # 记录超时结果
                research_span.set_attribute('final_iteration', self.max_iterations)
                research_span.set_attribute('success', False)
                research_span.set_attribute('reason', 'max_iterations_reached')
                
                logfire.warn(
                    'Research reached max iterations',
                    topic=topic,
                    max_iterations=self.max_iterations
                )
                return result

    def _combine_feedback(self, depth_result, review_result) -> str:
        """合并两个验证器的反馈"""
        feedbacks = []

        if not depth_result.passed and depth_result.feedback:
            feedbacks.append(depth_result.feedback)

        if not review_result.passed and review_result.feedback:
            feedbacks.append(review_result.feedback)

        combined = "\n\n---\n\n".join(feedbacks)

        return (
            f"**验证未通过，请继续探索**\n\n"
            f"{combined}\n\n"
            f"**请根据上述反馈继续研究，进入更多帖子并收集更多数据。**"
        )
