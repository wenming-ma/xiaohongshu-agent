"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容
"""
import os
from pydantic_ai import Agent
from pydantic_ai.mcp import load_mcp_servers
from ..models.schemas import ResearchResult


class ResearchAgent:
    """小红书研究 Agent"""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
        """
        初始化研究 Agent

        Args:
            model: 使用的模型名称
        """
        # 从环境变量获取 API Key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        self.mcp_servers = None
        self.agent = Agent(
            model=model,
            result_type=ResearchResult,
            system_prompt="""你是小红书研究专家。

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

**浏览器操作指南**：
1. 导航到小红书搜索页面
2. 输入搜索关键词
3. 浏览前10-15条笔记
4. 进入每条笔记阅读详情和评论
5. 提取结构化数据"""
        )

    async def initialize_mcp(self) -> None:
        """初始化 Playwright MCP 服务器"""
        print("   🌐 初始化 Playwright MCP Server...")

        self.mcp_servers = await load_mcp_servers({
            "playwright": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp"],
                "env": {
                    "HEADLESS": "false",  # 显示浏览器窗口
                    "BROWSER_TYPE": "chromium",
                    "USER_DATA_DIR": "./browser-sessions/xiaohongshu"
                }
            }
        })

        # 将 MCP 工具注册到 agent
        if self.mcp_servers:
            self.agent.toolsets = list(self.mcp_servers.values())
            print("   ✅ MCP Server 已启动")
        else:
            raise RuntimeError("MCP Server 初始化失败")

    async def research(self, topic: str, target_audience: str) -> ResearchResult:
        """
        执行研究任务

        Args:
            topic: 研究主题
            target_audience: 目标受众

        Returns:
            ResearchResult: 研究结果
        """
        if not self.mcp_servers:
            await self.initialize_mcp()

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
        result = await self.agent.run(prompt)

        return result.data
