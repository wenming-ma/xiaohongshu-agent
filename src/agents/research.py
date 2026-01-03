"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容
内置 Reflexion 循环：生成 → 审核 → 修订 → 循环直到通过
"""
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.messages import ModelRequest, UserPromptPart
from ..models.schemas import ResearchResult, ReviewResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.retry_handler import with_retry
from ..config.settings import RetryConfig, ReviewConfig, PathConfig
from prompts import get_system_prompt, get_user_prompt


class ResearchAgent:
    """小红书研究 Agent（带 Reflexion 循环）"""

    def __init__(self, max_iterations: int = None):
        """
        初始化研究 Agent

        Args:
            max_iterations: 最大审核迭代次数，默认使用配置
        """
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS

        # 获取带 HTTP 重试的 Model（max_retries=5）
        model = get_anthropic_model()

        # 🔑 创建 Playwright MCP Server 实例
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp'],
            env={
                'HEADLESS': 'false',  # 显示浏览器窗口
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_XHS
            },
            tool_prefix='playwright',  # 工具名前缀，避免冲突
            cache_tools=True,  # 缓存工具列表，提高性能
            max_retries=RetryConfig.MCP_RETRIES,
        )

        # 生成 Agent（带 MCP 工具）
        self.generator = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.mcp_server],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("research"),),
        )

        # 审核 Agent（纯推理，独立视角）
        self.reviewer = Agent(
            model=model,
            output_type=ReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("research_review"),),
        )

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

    async def _review(self, result: ResearchResult, topic: str, target_audience: str) -> ReviewResult:
        """
        审核研究结果

        Args:
            result: 研究结果
            topic: 研究主题
            target_audience: 目标受众

        Returns:
            ReviewResult: 审核结果
        """
        review_prompt = get_user_prompt(
            "research_review",
            topic=topic,
            target_audience=target_audience,
            research=result.model_dump_json(indent=2)
        )
        review_result = await self.reviewer.run(review_prompt)
        return review_result.output

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def research(self, topic: str, target_audience: str) -> ResearchResult:
        """
        执行研究任务（带 Reflexion 循环 + 外层重试）

        Args:
            topic: 研究主题
            target_audience: 目标受众

        Returns:
            ResearchResult: 研究结果（已通过审核或达到最大迭代次数）
        """
        messages = []  # 消息历史
        result = None
        review = None

        for i in range(self.max_iterations):
            # 1. 生成或继续修订
            if i == 0:
                prompt = get_user_prompt(
                    "research",
                    topic=topic,
                    target_audience=target_audience
                )
                print("   🔍 开始搜索和分析...")
            else:
                # 将审核反馈注入消息历史
                feedback_message = (
                    f"审核未通过，请继续搜索补充数据。\n\n"
                    f"**审核反馈**：{review.summary}\n\n"
                    f"**具体问题**：\n"
                )
                for issue in review.issues:
                    feedback_message += f"- [{issue.severity}] {issue.description}: {issue.suggestion}\n"

                messages.append(ModelRequest(parts=[
                    UserPromptPart(feedback_message)
                ]))
                prompt = "请根据反馈继续搜索，补充不足的数据。注意保留已有的有效数据。"
                print(f"   🔄 根据反馈继续搜索 (第{i+1}轮)...")

            # 执行生成
            run_result = await self.generator.run(prompt, message_history=messages)
            result = run_result.output
            messages.extend(run_result.new_messages())  # 保留历史

            # 2. 审核
            print(f"   🔍 审核研究结果 (第{i+1}轮)...")
            review = await self._review(result, topic, target_audience)

            # 3. 通过则返回
            if review.passed:
                print(f"   ✅ 研究审核通过 (第{i+1}轮)")
                print(f"      - 实体: {len(result.entities)} 个")
                print(f"      - 案例: {len(result.cases)} 个")
                print(f"      - 评分: {review.score:.1f}/100")
                return result

            # 未通过，打印反馈
            print(f"   ⚠️  研究审核未通过 (第{i+1}轮): {review.summary}")
            for issue in review.issues:
                print(f"      - [{issue.severity}] {issue.description}")

        # 达到最大迭代次数
        print(f"   ⚠️  达到最大迭代次数 ({self.max_iterations})，返回当前结果")
        return result

    async def close(self):
        """关闭 MCP Server 连接"""
        pass
