"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容
"""
import os
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from ..models.schemas import ResearchResult


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
        )

        # 🔑 在 Agent 构造时直接注册 MCP 工具（官方推荐）
        self.agent = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.mcp_server],  # ✅ 工具在构造时注册
            system_prompt=("""你是小红书研究专家。

**🔧 调试信息**：
系统会在首次调用时列出所有可用工具，请确认你能看到这些工具。

**可用工具**：
你现在拥有完整的浏览器控制能力（通过 Playwright MCP）：
- playwright_navigate: 导航到 URL
- playwright_click: 点击元素
- playwright_type: 输入文本
- playwright_wait: 等待页面加载
- playwright_read_page: 读取页面内容（可访问性树）
- playwright_find: 查找页面元素
- playwright_screenshot: 截图
- playwright_scroll: 滚动页面

**任务**：
使用浏览器工具搜索、阅读帖子和评论，提取有用信息。

**重点关注**：
- 具体公司名（不要泛泛而谈）
- 真实案例（用户的实际经历）
- 价格、时间、地点等具体细节
- 评论区的补充信息

**数据提取要求**：
1. entities: 提取实体信息（公司、价格、地点等）
   格式: [{"type": "company", "name": "公司名", "issue": "问题"}]

2. cases: 提取具体案例
   格式: [{"company": "公司", "experience": "经历", "source": "来源"}]

3. keywords: 提取高频关键词

4. credibility: 评估信息可信度
   - high: 多个独立来源证实，有具体细节
   - medium: 部分来源，细节较少
   - low: 单一来源或过于笼统

5. summary: 总结研究发现（3-5句话）

**浏览器操作流程**：
1. 使用 playwright_navigate 访问 https://www.xiaohongshu.com
2. 使用 playwright_find 找到搜索框
3. 使用 playwright_type 输入搜索关键词
4. 使用 playwright_click 点击搜索按钮
5. 使用 playwright_read_page 读取搜索结果
6. 依次点击前 10-15 条笔记
7. 在每条笔记中：
   - 使用 playwright_read_page 读取标题和正文
   - 向下滚动到评论区
   - 读取前 20 条评论
8. 提取结构化数据

**重要提示**：
- 充分利用所有可用的浏览器工具
- 如果某个元素难以定位，使用 playwright_screenshot 截图辅助
- 等待页面加载完成后再操作
- 评论区可能需要 playwright_scroll 才能加载更多内容
- 工具名称都有 'playwright_' 前缀""",)
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

        prompt = f"""
**研究任务**：搜索小红书关于 "{topic}" 的内容

**目标受众**：{target_audience}

**具体步骤**：
1. 打开小红书网站 (xiaohongshu.com)
2. 搜索关键词：{topic} {target_audience}
3. 浏览前 10-15 条笔记
4. 进入每条笔记查看：
   - 标题和正文
   - 评论区（前 20 条评论）
5. 提取以下信息：
   - 具体公司名称（至少 5 家）
   - 真实案例（至少 3 个详细案例）
   - 高频关键词
   - 评估信息可信度

**输出要求**：
- entities: 至少 5 个实体
- cases: 至少 3 个案例
- keywords: 5-10 个关键词
- summary: 3-5 句话总结
- credibility: 基于数据质量评估
- data_points: 统计总共收集的数据点数量

开始执行！
"""

        print("   🔍 开始搜索和分析...")

        # 🔑 MCP Server 会在第一次使用工具时自动连接
        result = await self.agent.run(prompt)

        return result.output

    async def close(self):
        """关闭 MCP Server 连接"""
        # MCP Server 实现了异步上下文管理器
        # 如果需要手动关闭，可以调用此方法
        pass
