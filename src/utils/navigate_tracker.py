"""
MCP 工具调用追踪器
用于跟踪 playwright_navigate 调用，统计帖子详情页访问次数
"""
import re
from urllib.parse import urlsplit, urlunsplit
from typing import Any, List, Callable
from pydantic_ai import RunContext, WrapperToolset, ToolsetTool
from .logger import get_logger

logger = get_logger(__name__)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 实例级存储，避免复杂共享/深拷贝逻辑
        self._visited_urls_storage: List[str] = []
        self._post_detail_urls_storage: List[str] = []

    def visit_and_replace(self, visitor: Callable) -> "NavigateTracker":
        """
        关键：避免 pydantic-ai 在构建运行时 toolset 时对 WrapperToolset 进行 dataclasses.replace()
        产生"新实例"，导致追踪数据写入到克隆实例而外部读取仍是旧实例（表现为追踪数量始终为 0）。

        我们通过"就地更新 wrapped 并返回 self"来保持同一实例的追踪状态可见。
        """
        # 让 visitor 继续作用于底层 toolset（通常是 MCPServerStdio 等 leaf toolset）
        if hasattr(self.wrapped, "visit_and_replace"):
            self.wrapped = self.wrapped.visit_and_replace(visitor)  # type: ignore[attr-defined]
        return self

    @property
    def _visited_urls(self) -> List[str]:
        """访问 URL 列表"""
        return self._visited_urls_storage
    
    @property
    def _post_detail_urls(self) -> List[str]:
        """帖子详情页 URL 列表"""
        return self._post_detail_urls_storage

    _REVISIT_HINT = (
        "\n\n⚠️ 提醒：此页面已在之前访问过，其内容已被记录。"
        "请返回搜索结果页面，向下滚动加载更多结果，或更换关键词搜索，选择未访问过的帖子继续研究。"
    )

    def _is_navigate_call(self, name: str) -> bool:
        """判断工具调用是否是导航操作"""
        return (
            name == 'playwright_navigate'
            or name == 'playwright_browser_navigate'
            or (name.startswith('playwright_') and 'navigate' in name)
        )

    def _get_navigate_url(self, tool_args: dict[str, Any]) -> str:
        """从工具参数中提取导航目标 URL"""
        return (
            tool_args.get('url')
            or tool_args.get('target')
            or tool_args.get('href')
            or ''
        )

    def _append_revisit_hint(self, result: Any, url: str) -> Any:
        """在工具返回结果中追加重复访问提示"""
        logger.info("[追踪] 重复访问: %s", url[:80])
        if isinstance(result, str):
            return result + self._REVISIT_HINT
        return str(result) + self._REVISIT_HINT

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
            工具执行结果（重复访问时追加提示）
        """
        # 在执行前检查是否重复访问
        is_revisit = False
        if self._is_navigate_call(name):
            url = self._get_navigate_url(tool_args)
            normalized = self._normalize_url(url)
            if normalized and normalized in self._visited_urls:
                is_revisit = True

        # 执行工具调用
        result = await super().call_tool(name, tool_args, ctx, tool)

        # 追踪 navigate 调用
        if self._is_navigate_call(name):
            url = self._get_navigate_url(tool_args)
            self._track_navigation(url)

        # 对于点击等导航操作，解析工具返回内容中的 Page URL
        self._track_from_result(result)

        # 重复访问时追加提示
        if is_revisit:
            result = self._append_revisit_hint(result, normalized)

        return result

    def _normalize_url(self, url: str) -> str:
        """
        规范化 URL：
        - 去掉 query / fragment（如 xsec_token 等），减少长度并提升去重稳定性
        - 仅保留 scheme://netloc/path
        """
        if not url:
            return url
        try:
            parts = urlsplit(url)
            # 如果没有 scheme/netloc（例如工具返回的相对路径），保持原样
            if not parts.scheme or not parts.netloc:
                # 仍然尽量去掉 query/fragment
                if "?" in url:
                    url = url.split("?", 1)[0]
                if "#" in url:
                    url = url.split("#", 1)[0]
                return url
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except Exception:
            # 保守兜底：字符串切割
            if "?" in url:
                url = url.split("?", 1)[0]
            if "#" in url:
                url = url.split("#", 1)[0]
            return url

    def _track_navigation(self, url: str) -> None:
        """
        追踪导航 URL

        Args:
            url: 导航目标 URL
        """
        url = self._normalize_url(url)
        if not url:
            return

        if url in self._visited_urls:
            return

        self._visited_urls.append(url)

        # 检查是否是帖子详情页
        if self._is_post_detail_url(url) and url not in self._post_detail_urls:
            self._post_detail_urls.append(url)
            logger.debug(f"[追踪] 帖子详情页: {url[:80]}...")

    def _track_from_result(self, result: Any) -> None:
        """从工具返回内容里提取 URL（用于 click/snapshot 后的页面状态）"""
        for url in self._extract_urls(result):
            self._track_navigation(url)

    def _extract_urls(self, payload: Any) -> list[str]:
        """递归从工具响应里提取 URL（包含 Page URL 行）"""
        urls: list[str] = []
        texts: list[str] = []

        if payload is None:
            return urls

        if isinstance(payload, str):
            texts.append(payload)
        elif isinstance(payload, dict):
            for key, value in payload.items():
                if key in ("url", "href", "page_url") and isinstance(value, str):
                    urls.append(value)
                elif key == "content":
                    urls.extend(self._extract_urls(value))
                elif isinstance(value, str):
                    texts.append(value)
                else:
                    urls.extend(self._extract_urls(value))
        elif isinstance(payload, list):
            for item in payload:
                urls.extend(self._extract_urls(item))
        elif hasattr(payload, "content"):
            urls.extend(self._extract_urls(getattr(payload, "content")))
        else:
            # 尝试读取常见对象属性（TextPart 等）
            for attr in ("text", "markdown", "url", "href", "page_url", "message"):
                if hasattr(payload, attr):
                    value = getattr(payload, attr)
                    if isinstance(value, str):
                        texts.append(value)
                    else:
                        urls.extend(self._extract_urls(value))

        if texts:
            text_blob = "\n".join(texts)
            for line in text_blob.splitlines():
                if "Page URL:" in line:
                    candidate = line.split("Page URL:", 1)[-1].strip()
                    urls.append(candidate)
                else:
                    match = re.search(r"https?://[^\s)>\]]+", line)
                    if match:
                        urls.append(match.group(0))

        return urls

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
        stats = {
            "total_navigations": len(self._visited_urls),
            "post_detail_count": len(self._post_detail_urls),
            "post_detail_urls": self._post_detail_urls.copy(),
        }
        return stats

    def reset(self, force: bool = False) -> None:
        """
        重置追踪数据

        只有 force=True 时才清空，用于防止 Agent 在每次 run 后的自动 reset
        抹掉追踪状态。研究开始前手动调用 reset(force=True) 即可。
        """
        if not force:
            return

        self._visited_urls.clear()
        self._post_detail_urls.clear()
