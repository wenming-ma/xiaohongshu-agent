"""
发布 Agent - ML 模型风格
使用 Playwright MCP Server 自动发布内容到小红书平台

使用方式：
    agent = PublisherAgent()
    result = await agent.forward(content, images, output_dir)
"""
from pathlib import Path
from typing import List
from datetime import datetime
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits
from ...models.schemas import XHSContent, PublishResult
from ...utils.minimax_provider import get_minimax_model
from ...utils.retry_handler import with_retry
from ...utils.logger import get_logger
from ...config.settings import RetryConfig, PathConfig, TimeoutConfig, PublishConfig
from ...infra.login_agent import LoginAgent
from .prompts import publisher_system_prompt, publisher_user_prompt

logger = get_logger(__name__)


class PublisherAgent:
    """
    小红书发布 Agent（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口

    使用方式：
        agent = PublisherAgent()
        result = await agent.forward(content, images, output_dir)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化发布 Agent"""
        self._init_mcp_server()
        self._init_tools()
        self._init_publisher()

    def _init_mcp_server(self):
        """初始化 Playwright MCP Server"""
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_XHS
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )

    def _init_tools(self):
        """初始化工具集"""
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)

    def _init_publisher(self):
        """初始化发布 Agent"""
        model = get_minimax_model()
        function_tools = [self.login_agent.get_tool()]

        self.publisher = Agent(
            model=model,
            output_type=PublishResult,
            toolsets=[self.mcp_server],
            tools=function_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(publisher_system_prompt(),),
        )

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    @with_retry(max_retries=PublishConfig.MAX_RETRIES, initial_delay=PublishConfig.INITIAL_DELAY)
    async def forward(
        self,
        content: XHSContent,
        images: List[Path],
        output_dir: Path
    ) -> PublishResult:
        """
        发布内容到小红书（主入口）

        类似 PyTorch 的 forward 方法。

        Args:
            content: 小红书内容（标题、正文、标签等）
            images: 图片路径列表（按顺序：封面 + 详情图）
            output_dir: 输出目录（用于保存发布记录）

        Returns:
            PublishResult: 发布结果
        """
        logger.info("准备发布到小红书: %s (%d 张图片)", content.title, len(images))

        try:
            # 验证图片顺序
            self._validate_images(images)

            # 构建用户提示词
            user_prompt = self._build_prompt(content, images)

            # 执行发布
            logger.info("Agent 开始执行发布流程...")
            async with self.mcp_server:
                result = await self.publisher.run(user_prompt, usage_limits=UsageLimits(request_limit=None))
                publish_result: PublishResult = result.output

            # 处理结果
            return self._handle_result(publish_result)

        except Exception as e:
            return self._handle_error(e, content, images)

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def _validate_images(self, images: List[Path]) -> None:
        """验证图片顺序"""
        if images:
            first_image_name = images[0].stem
            if not first_image_name.startswith('cover'):
                logger.warning("第一张图片不是封面图: %s", first_image_name)

        for i, img in enumerate(images):
            logger.debug("图片 %d: %s", i + 1, img.name)

    def _build_prompt(self, content: XHSContent, images: List[Path]) -> str:
        """构建用户提示词"""
        image_paths_str = "\n".join([
            f"   {i+1}. {str(img)} [{img.stem}]"
            for i, img in enumerate(images)
        ])

        # 预先拼接正文、行动号召和话题，避免 LLM 在浏览器操作时遗漏或覆盖
        full_body = content.body

        # 添加行动号召
        if content.call_to_action:
            full_body = f"{full_body}\n\n{content.call_to_action}"

        # 添加话题到正文末尾（小红书话题格式：#话题名 空格分隔）
        if content.hashtags:
            hashtags_formatted = " ".join([f"#{tag}" for tag in content.hashtags])
            full_body = f"{full_body} {hashtags_formatted}"

        return publisher_user_prompt(
            title=content.title,
            body=full_body,
            hashtags="",  # 话题已拼接到正文中，传空字符串
            image_count=len(images),
            image_paths=image_paths_str,
        )

    def _handle_result(self, publish_result: PublishResult) -> PublishResult:
        """处理发布结果"""
        if publish_result.published:
            logger.info("发布成功: %s", publish_result.post_url or "已发布")
        else:
            logger.warning("发布失败: %s", publish_result.error_message)
            raise RuntimeError(f"发布失败: {publish_result.error_message}")

        return publish_result

    def _handle_error(
        self,
        e: Exception,
        content: XHSContent,
        images: List[Path]
    ) -> PublishResult:
        """处理发布异常"""
        error_msg = str(e)
        logger.error("发布异常: %s", error_msg)

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
