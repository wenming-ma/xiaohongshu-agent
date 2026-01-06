"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容

验证流程：
1. generator.run() 执行研究
2. ResearchDepthValidator 验证帖子数量
3. ResearchReviewValidator 验证数据质量
4. 两个都通过 → 返回结果
5. 任一失败 → 注入反馈，继续循环（保持消息历史）
"""
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.messages import ModelRequest, UserPromptPart
from ..models.schemas import ResearchResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.retry_handler import with_retry
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
        # 获取带 HTTP 重试的 Model
        model = get_anthropic_model()

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

        # 研究生成 Agent（带 MCP 工具）
        self.generator = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.mcp_server],
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
        validation_context = {
            "topic": topic,
            "target_audience": target_audience
        }

        print(f"\n📚 开始研究：{topic}")
        print(f"   目标受众：{target_audience}")
        print(f"   最大迭代次数：{self.max_iterations}")

        async with self.mcp_server:  # 浏览器保持打开
            for iteration in range(self.max_iterations):
                print(f"\n{'='*50}")
                print(f"🔄 第 {iteration + 1}/{self.max_iterations} 轮研究")
                print(f"{'='*50}")

                # 1. 执行研究
                if iteration == 0:
                    # 首轮：使用初始提示词
                    agent_result = await self.generator.run(
                        initial_prompt,
                        message_history=message_history
                    )
                else:
                    # 后续轮：消息历史已包含反馈
                    agent_result = await self.generator.run(
                        message_history=message_history
                    )

                result = agent_result.output

                # 更新消息历史
                message_history = list(agent_result.all_messages())

                print(f"\n📊 本轮研究结果：")
                print(f"   - 帖子数量: {result.posts_researched}")
                print(f"   - 关键信息数量: {len(result.key_infos)}")
                print(f"   - 案例数量: {len(result.cases)}")
                print(f"   - 评论区数据占比: {result.comment_data_ratio:.0%}")

                # 2. 验证帖子数量
                print(f"\n🔍 验证研究深度...")
                depth_result = await self.depth_validator.validate(
                    result, validation_context
                )

                # 3. 验证数据质量
                print(f"🔍 验证数据质量...")
                review_result = await self.review_validator.validate(
                    result, validation_context
                )

                # 4. 两个都通过？
                if depth_result.passed and review_result.passed:
                    print(f"\n✅ 研究验证全部通过！")
                    print(f"   - 深度验证评分: {depth_result.score:.1f}/100")
                    print(f"   - 质量验证评分: {review_result.score:.1f}/100")
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
