"""
MCP 工具调用追踪器
用于跟踪 playwright_navigate 调用，统计帖子详情页访问次数
"""
from typing import Any, List
from pydantic_ai import RunContext, WrapperToolset, ToolsetTool


class NavigateTracker(WrapperToolset):
    """
    导航追踪器 - 包装 MCP Server 以追踪 playwright_navigate 调用

    用法：
        mcp_server = MCPServerStdio(...)
        tracker = NavigateTracker(mcp_server)
        agent = Agent(toolsets=[tracker])

        # 执行后获取追踪数据
        post_count = tracker.get_post_detail_count()
    """

    # 小红书帖子详情页 URL 特征
    POST_DETAIL_PATTERNS = [
        '/explore/',      # 探索页帖子详情
        '/discovery/item/',  # 发现页帖子详情
    ]

    @property
    def _visited_urls(self) -> List[str]:
        """延迟初始化的访问 URL 列表"""
        if not hasattr(self, '_visited_urls_storage'):
            self._visited_urls_storage = []
        return self._visited_urls_storage
    
    @property
    def _post_detail_urls(self) -> List[str]:
        """延迟初始化的帖子详情页 URL 列表"""
        if not hasattr(self, '_post_detail_urls_storage'):
            self._post_detail_urls_storage = []
        return self._post_detail_urls_storage

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext,
        tool: ToolsetTool
    ) -> Any:
        """
        拦截工具调用，追踪导航操作

        Args:
            name: 工具名称（如 playwright_navigate）
            tool_args: 工具参数
            ctx: 运行上下文
            tool: 工具定义

        Returns:
            工具执行结果
        """
        # 先执行工具调用
        result = await super().call_tool(name, tool_args, ctx, tool)

        # 追踪 navigate 调用
        if name == 'playwright_navigate':
            url = tool_args.get('url', '')
            self._track_navigation(url)

        return result

    def _track_navigation(self, url: str) -> None:
        """
        追踪导航 URL

        Args:
            url: 导航目标 URL
        """
        if not url:
            return

        self._visited_urls.append(url)

        # 检查是否是帖子详情页
        if self._is_post_detail_url(url):
            self._post_detail_urls.append(url)
            print(f"   [追踪] 帖子详情页: {url[:80]}...")

    def _is_post_detail_url(self, url: str) -> bool:
        """
        判断 URL 是否是帖子详情页

        Args:
            url: URL 字符串

        Returns:
            是否是帖子详情页
        """
        return any(pattern in url for pattern in self.POST_DETAIL_PATTERNS)

    def get_post_detail_count(self) -> int:
        """
        获取访问的帖子详情页数量

        Returns:
            帖子详情页访问次数
        """
        return len(self._post_detail_urls)

    def get_post_detail_urls(self) -> List[str]:
        """
        获取所有访问过的帖子详情页 URL

        Returns:
            帖子详情页 URL 列表
        """
        return self._post_detail_urls.copy()

    def get_all_visited_urls(self) -> List[str]:
        """
        获取所有访问过的 URL

        Returns:
            所有 URL 列表
        """
        return self._visited_urls.copy()

    def get_stats(self) -> dict:
        """
        获取追踪统计信息

        Returns:
            统计信息字典
        """
        return {
            "total_navigations": len(self._visited_urls),
            "post_detail_count": len(self._post_detail_urls),
            "post_detail_urls": self._post_detail_urls.copy(),
        }

    def reset(self) -> None:
        """重置追踪数据"""
        self._visited_urls.clear()
        self._post_detail_urls.clear()
