"""
发布 Agent
使用 Playwright MCP Server 自动发布内容到小红书平台
"""
from pathlib import Path
from typing import List
from datetime import datetime
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from ..models.schemas import XHSContent, PublishResult
from ..utils.anthropic_provider import get_anthropic_model
from ..utils.retry_handler import with_retry
from ..config.settings import RetryConfig, PathConfig, TimeoutConfig, PublishConfig
from prompts import get_system_prompt, get_user_prompt


class PublisherAgent:
    """小红书发布 Agent"""

    def __init__(self):
        """初始化发布 Agent"""

        # 获取带 HTTP 重试的 Model
        model = get_anthropic_model()

        # 创建 Playwright MCP Server 实例（复用小红书浏览器会话）
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

        # Publisher Agent（执行发布操作）
        self.publisher = Agent(
            model=model,
            output_type=str,  # 返回发布状态描述
            toolsets=[self.mcp_server],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("publisher"),),
        )

    @with_retry(max_retries=PublishConfig.MAX_RETRIES, initial_delay=PublishConfig.INITIAL_DELAY)
    async def publish(
        self,
        content: XHSContent,
        images: List[Path],
        output_dir: Path
    ) -> PublishResult:
        """
        发布内容到小红书

        Args:
            content: 小红书内容（标题、正文、标签等）
            images: 图片路径列表（按顺序：封面 + 详情图）
            output_dir: 输出目录（用于保存发布记录）

        Returns:
            PublishResult: 发布结果
        """
        print(f"\n   📤 准备发布到小红书...")
        print(f"   - 标题: {content.title}")
        print(f"   - 图片数量: {len(images)} 张")

        try:
            # 构建用户提示词
            image_paths_str = "\n".join([f"   {i+1}. {str(img)}" for i, img in enumerate(images)])
            hashtags_str = ", ".join(content.hashtags)

            user_prompt = get_user_prompt(
                "publisher",
                title=content.title,
                body=content.body,
                hashtags=hashtags_str,
                call_to_action=content.call_to_action,
                image_count=len(images),
                image_paths=image_paths_str
            )

            # 执行发布（Agent 会使用 Playwright MCP 工具）
            print(f"\n   🤖 Agent 开始执行发布流程...")

            async with self.mcp_server:
                result = await self.publisher.run(user_prompt)
                status_message = result.output

            print(f"\n   📋 Agent 执行结果:")
            print(f"   {status_message}")

            # 判断是否成功（基于 Agent 输出）
            success_keywords = ["成功", "SUCCESS", "发布完成", "published"]
            is_success = any(keyword in status_message for keyword in success_keywords)

            if is_success:
                # 尝试从输出中提取发布链接（如果有）
                post_url = self._extract_url_from_message(status_message)

                return PublishResult(
                    published=True,
                    platform="xiaohongshu",
                    publish_time=datetime.now().isoformat(),
                    post_url=post_url,
                    error_message="",
                    retry_count=0
                )
            else:
                # 发布失败，触发重试
                raise RuntimeError(f"发布失败: {status_message}")

        except Exception as e:
            error_msg = str(e)
            print(f"\n   ❌ 发布异常: {error_msg}")

            # 返回失败结果（包含元数据供手动重试）
            return PublishResult(
                published=False,
                platform="xiaohongshu",
                publish_time=datetime.now().isoformat(),
                post_url="",
                error_message=error_msg,
                retry_count=PublishConfig.MAX_RETRIES,
                content_snapshot=content.model_dump(),
                image_paths=[str(img) for img in images]
            )

    def _extract_url_from_message(self, message: str) -> str:
        """
        从 Agent 输出消息中提取小红书链接

        Args:
            message: Agent 输出消息

        Returns:
            str: 提取的 URL，如果没有则返回空字符串
        """
        import re

        # 匹配小红书链接模式
        patterns = [
            r'https?://www\.xiaohongshu\.com/explore/[a-zA-Z0-9]+',
            r'https?://www\.xiaohongshu\.com/discovery/item/[a-zA-Z0-9]+',
            r'https?://creator\.xiaohongshu\.com/publish/success\?id=[a-zA-Z0-9]+'
        ]

        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return match.group(0)

        return ""
