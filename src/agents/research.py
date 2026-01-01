"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容
"""
import os
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from ..models.schemas import ResearchResult
from prompts import get_system_prompt, get_user_prompt


class ResearchAgent:
    """小红书研究 Agent"""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        """
        初始化研究 Agent

        Args:
            model: 使用的模型名称
        """
        # 从环境变量获取 API Key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        # 🔑 创建 Playwright MCP Server 实例
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp'],
            env={
                'HEADLESS': 'false',  # 显示浏览器窗口
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': './browser-sessions/xiaohongshu'
            },
            tool_prefix='playwright',  # 工具名前缀，避免冲突
            cache_tools=True,  # 缓存工具列表，提高性能
            max_retries=5,  # 🔑 增加工具重试次数（浏览器操作可能不稳定）
        )

        # 🔑 在 Agent 构造时直接注册 MCP 工具（官方推荐）
        self.agent = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.mcp_server],  # ✅ 工具在构造时注册
            instrument=True,  # ✅ 启用 Logfire 可观测性
            retries=3,  # ✅ 增加重试次数（浏览器操作可能需要更多重试）
            system_prompt=(get_system_prompt("research"),),  # ✅ 从 YAML 加载
        )

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        print("\n   🔧 正在检查可用工具...")

        try:
            # 使用 MCP Server 的 list_tools 方法
            # 注意：需要在异步上下文中调用
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

    async def research(self, topic: str, target_audience: str) -> ResearchResult:
        """
        执行研究任务

        Args:
            topic: 研究主题
            target_audience: 目标受众

        Returns:
            ResearchResult: 研究结果
        """
        # 首次运行时列出工具
        await self.list_tools()

        # 从 YAML 加载并渲染 user prompt
        prompt = get_user_prompt(
            "research",
            topic=topic,
            target_audience=target_audience
        )

        print("   🔍 开始搜索和分析...")

        # 🔑 MCP Server 会在第一次使用工具时自动连接
        result = await self.agent.run(prompt)

        return result.output

    async def close(self):
        """关闭 MCP Server 连接"""
        # MCP Server 实现了异步上下文管理器
        # 如果需要手动关闭，可以调用此方法
        pass
