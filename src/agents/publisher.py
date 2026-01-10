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
from ..utils.model_factory import get_model
from ..utils.retry_handler import with_retry
from ..utils.logger import get_logger
from ..config.settings import RetryConfig, PathConfig, TimeoutConfig, PublishConfig
from prompts import get_system_prompt, get_user_prompt
from .login import LoginAgent

logger = get_logger(__name__)


class PublisherAgent:
    """小红书发布 Agent"""

    def __init__(self):
        """初始化发布 Agent"""

        # 获取带 HTTP 重试的 Model（根据配置选择 Anthropic 或 OpenRouter）
        model = get_model()

        # 创建 Playwright MCP Server 实例（复用小红书浏览器会话）
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
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

        # LoginAgent - 用于处理登录/注册（复用同一个 Playwright MCP/浏览器会话）
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)

        # Publisher Agent（结构化输出：直接返回 PublishResult）
        self.publisher = Agent(
            model=model,
            output_type=PublishResult,
            toolsets=[self.mcp_server],
            tools=[self.login_agent.get_tool()],  # 登录/注册工具
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
        logger.info("准备发布到小红书: %s (%d 张图片)", content.title, len(images))

        try:
            # 验证图片顺序（第一张必须是 cover）
            if images:
                first_image_name = images[0].stem
                if not first_image_name.startswith('cover'):
                    logger.warning("第一张图片不是封面图: %s", first_image_name)

            # 记录图片上传顺序
            for i, img in enumerate(images):
                logger.debug("图片 %d: %s", i + 1, img.name)

            # 构建用户提示词（带类型标注）
            image_paths_str = "\n".join([
                f"   {i+1}. {str(img)} [{img.stem}]"
                for i, img in enumerate(images)
            ])
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
            logger.info("Agent 开始执行发布流程...")

            async with self.mcp_server:
                result = await self.publisher.run(user_prompt)
                publish_result: PublishResult = result.output

            # Agent 直接返回结构化的 PublishResult
            if publish_result.published:
                logger.info("发布成功: %s", publish_result.post_url or "已发布")
            else:
                logger.warning("发布失败: %s", publish_result.error_message)
                # 发布失败，触发重试
                raise RuntimeError(f"发布失败: {publish_result.error_message}")

            return publish_result

        except Exception as e:
            error_msg = str(e)
            logger.error("发布异常: %s", error_msg)

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
