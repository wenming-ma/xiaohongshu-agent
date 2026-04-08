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
from pydantic_ai.usage import UsageLimits
from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import XHSContent, PublishResult
from ....utils.providers import get_text_model
from ....utils.retry_handler import with_retry
from ....utils.logger import get_logger
from ....config.settings import RetryConfig, PathConfig, PublishConfig
from ...shared import create_shared_playwright_mcp_server, BodyInjectTool
from ...shared.login import create_login_tool
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

    def init_mcp_server(self, output_dir: Path | None = None):
        """初始化 Playwright MCP Server"""
        self.mcp_server = create_shared_playwright_mcp_server(
            output_dir=output_dir or PathConfig.DOWNLOADS_DIR,
            tool_prefix='playwright',
            headless=False,
        )

    def init_tools(self) -> None:
        """初始化工具集"""
        self.login_tool = create_login_tool(self.mcp_server)
        self.body_inject_tool = BodyInjectTool(self.mcp_server)

    def init_agent(self) -> None:
        """初始化发布 Agent"""
        model = get_text_model()
        function_tools = [self.login_tool, self.body_inject_tool.get_tool()]

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

        # 先做确定性输入校验，避免无意义的浏览器初始化和重试
        self._check_images(images)

        # 重新初始化 MCP Server，使其 cwd 指向帖子目录，
        # 这样 Playwright 才能访问该目录下的图片进行上传
        self.init_mcp_server(output_dir)
        self.init_tools()
        self.init_agent()

        # 绑定正文到注入工具
        full_body = content.body
        if content.call_to_action:
            full_body = f"{full_body}\n\n{content.call_to_action}"
        self.body_inject_tool.bind_body(full_body)

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
        if not images:
            raise ValueError("图片列表为空，无法发布")

        for img in images:
            if not img.exists():
                raise ValueError(f"图片文件不存在: {img}")

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

        # 话题通过推荐芯片单独添加，不拼接到正文中
        hashtags_str = "\n".join([f"   - {tag}" for tag in content.hashtags]) if content.hashtags else "无"

        return publisher_user_prompt(
            title=content.title,
            hashtags=hashtags_str,
            image_count=len(images),
            image_paths=image_paths_str,
        )
