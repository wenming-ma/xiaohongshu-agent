"""
自动截屏 MCP Server
在 Agent 结束时自动截屏，类似 C++ 析构函数

参考：LangGraph ExitStack 模式
"""
from typing import Callable, Awaitable, Optional, Any
from pathlib import Path
from datetime import datetime
from pydantic_ai.mcp import MCPServerStdio


class AutoScreenshotMCPServer(MCPServerStdio):
    """
    在退出时自动截屏的 MCP Server

    继承 MCPServerStdio，在 __aexit__ 中添加截屏逻辑。
    类似 C++ 析构函数的自动清理机制。

    用法:
        server = AutoScreenshotMCPServer(
            command='npx',
            args=['-y', '@playwright/mcp', '--output-dir', './output'],
            screenshot_dir=Path('./output'),
            screenshot_callback=my_callback,
            auto_screenshot=True,
        )
    """

    def __init__(
        self,
        *args,
        screenshot_dir: Optional[Path] = None,
        screenshot_callback: Optional[Callable[[Path], Awaitable[None]]] = None,
        auto_screenshot: bool = True,
        **kwargs
    ):
        """
        初始化自动截屏 MCP Server

        Args:
            *args: MCPServerStdio 的位置参数
            screenshot_dir: 截屏保存目录
            screenshot_callback: 截屏完成后的异步回调函数
            auto_screenshot: 是否启用自动截屏
            **kwargs: MCPServerStdio 的关键字参数
        """
        super().__init__(*args, **kwargs)

        # 配置参数
        self.screenshot_dir = screenshot_dir
        self.screenshot_callback = screenshot_callback
        self.auto_screenshot = auto_screenshot

        # 内部状态
        self._last_screenshot_path: Optional[Path] = None

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Optional[bool]:
        """
        析构函数 - 在关闭连接前自动截屏

        类似 C++ 析构函数，在对象销毁前执行清理操作。
        确保截屏在 MCP 连接关闭之前完成。
        """
        # 只在最后一次退出时截屏（引用计数变为 0）
        should_screenshot = (
            self.auto_screenshot
            and self.screenshot_dir
            and self._running_count == 1  # 即将变为 0
        )

        if should_screenshot:
            try:
                screenshot_path = await self._take_screenshot()
                self._last_screenshot_path = screenshot_path
                print(f"         📸 自动截屏完成: {screenshot_path.name}")

                if self.screenshot_callback:
                    await self.screenshot_callback(screenshot_path)
            except Exception as e:
                print(f"         ⚠️ 自动截屏失败: {e}")

        # 确保原始清理逻辑执行
        return await super().__aexit__(exc_type, exc_val, exc_tb)

    async def _take_screenshot(self) -> Path:
        """
        调用 browser_take_screenshot 工具截屏

        Returns:
            Path: 截屏文件的路径
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"gemini-state-{timestamp}.png"

        # 构建工具名称（考虑 tool_prefix）
        tool_name = "browser_take_screenshot"
        if self.tool_prefix:
            tool_name = f"{self.tool_prefix}_{tool_name}"

        # 通过 MCP 调用截屏工具
        await self.direct_call_tool(
            name="browser_take_screenshot",  # direct_call_tool 内部会处理 prefix
            args={"filename": filename, "type": "png"},
        )

        return self.screenshot_dir / filename

    @property
    def last_screenshot(self) -> Optional[Path]:
        """获取最后一次截屏的路径"""
        return self._last_screenshot_path
