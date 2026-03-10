"""
发布 Agent - ML 模型风格
使用 Playwright MCP Server 自动发布内容到小红书平台

使用方式：
    agent = PublisherAgent()
    result = await agent.forward(content, images, output_dir)
"""
from pathlib import Path
from typing import List, Any
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.usage import UsageLimits
from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import XHSContent, PublishResult
from .....utils.minimax_provider import get_minimax_model
from .....utils.retry_handler import with_retry
from .....utils.logger import get_logger
from .....config.settings import RetryConfig, PathConfig, TimeoutConfig, PublishConfig
from ..login import LoginAgent
from .prompts import publisher_system_prompt, publisher_user_prompt

logger = get_logger(__name__)


class PublisherAgent(BaseAgent):
    """小红书发布 Agent"""

    role = "发布专员"
    goal = "自动化发布内容到小红书平台"

    def __init__(self):
        """初始化发布 Agent"""
        self.init_mcp_server()
        super().__init__()

    def init_mcp_server(self):
        """初始化 Playwright MCP Server"""
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_SHARED
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )

    def init_tools(self) -> None:
        """初始化工具集"""
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)

    def init_agent(self) -> None:
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

        # 验证图片输入
        self._check_images(images)

        # 构建用户提示词
        user_prompt = self.build_prompt(content, images)

        # 执行发布
        publish_result = await self.step(user_prompt)

        # 验证并处理结果
        validation = await self.validate(publish_result)
        if not validation.passed:
            raise RuntimeError(validation.feedback)

        return publish_result

    # ========================================================================
    # 工作流子步骤
    # ========================================================================

    async def step(self, user_prompt: str) -> PublishResult:
        """
        工作流子步骤：执行发布

        Args:
            user_prompt: 用户提示词

        Returns:
            PublishResult: 发布结果
        """
        logger.info("Agent 开始执行发布流程...")
        async with self.mcp_server:
            result = await self.publisher.run(user_prompt, usage_limits=UsageLimits(request_limit=None))
            return result.output

    # ========================================================================
    # 验证方法
    # ========================================================================

    async def validate(self, output: Any) -> ValidationResult:
        """
        验证发布结果

        Args:
            output: PublishResult 实例

        Returns:
            ValidationResult: 验证结果
        """
        if not isinstance(output, PublishResult):
            return ValidationResult.failure("输出类型错误，期望 PublishResult")

        if output.published:
            logger.info("发布成功: %s", output.post_url or "已发布")
            return ValidationResult.success(f"发布成功: {output.post_url or '已发布'}")
        else:
            logger.warning("发布失败: %s", output.error_message)
            return ValidationResult.failure(f"发布失败: {output.error_message}")

    def _check_images(self, images: List[Path]) -> None:
        """检查图片输入（内部辅助方法）"""
        if images:
            first_image_name = images[0].stem
            if not first_image_name.startswith('cover'):
                logger.warning("第一张图片不是封面图: %s", first_image_name)

        for i, img in enumerate(images):
            logger.debug("图片 %d: %s", i + 1, img.name)

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def build_prompt(self, content: XHSContent, images: List[Path]) -> str:
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
