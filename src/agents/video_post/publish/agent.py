from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import XHSVideoContent, VideoPublishResult
from ....utils.providers import get_text_model
from ....utils.retry_handler import with_retry
from ....utils.logger import get_logger
from ....config.settings import RetryConfig, PathConfig, PublishConfig
from ...shared import create_shared_playwright_mcp_server, BodyInjectTool
from .prompts import publisher_system_prompt, publisher_user_prompt

logger = get_logger(__name__)


class PublisherAgent(BaseAgent):

    role = "视频发布专员"
    goal = "自动化发布视频到小红书平台"

    def __init__(self):
        self.init_mcp_server()
        super().__init__()

    def init_mcp_server(self, output_dir: Path | None = None):
        self.mcp_server = create_shared_playwright_mcp_server(
            output_dir=output_dir or PathConfig.DOWNLOADS_DIR,
            tool_prefix='playwright',
            headless=False,
        )

    def init_tools(self) -> None:
        self.body_inject_tool = BodyInjectTool(self.mcp_server)

    def init_agent(self) -> None:
        model = get_text_model()
        function_tools = [self.body_inject_tool.get_tool()]
        self.publisher = Agent(
            model=model,
            output_type=VideoPublishResult,
            toolsets=[self.mcp_server],
            tools=function_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(publisher_system_prompt(),),
        )

    @with_retry(max_retries=PublishConfig.MAX_RETRIES, initial_delay=PublishConfig.INITIAL_DELAY)
    async def forward(
        self,
        content: XHSVideoContent,
        video_path: Path,
        output_dir: Path,
    ) -> VideoPublishResult:
        logger.info("准备发布视频到小红书: %s", content.title)

        # 重新初始化 MCP Server，使其 cwd 指向帖子目录，
        # 这样 Playwright 才能访问该目录下的视频文件进行上传
        self.init_mcp_server(output_dir)
        self.init_tools()
        self.init_agent()

        self._check_video(video_path)

        # 绑定正文到注入工具
        full_body = content.body
        if content.call_to_action:
            full_body = f"{full_body}\n\n{content.call_to_action}"
        self.body_inject_tool.bind_body(full_body)

        user_prompt = self.build_prompt(content, video_path)
        publish_result = await self.step(user_prompt)

        validation = await self.validate(publish_result)
        if not validation.passed:
            raise RuntimeError(validation.feedback)

        return publish_result

    async def step(self, user_prompt: str) -> VideoPublishResult:
        logger.info("Agent 开始执行视频发布流程...")
        async with self.mcp_server:
            result = await self.publisher.run(user_prompt, usage_limits=UsageLimits(request_limit=None))
            return result.output

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, VideoPublishResult):
            return ValidationResult.failure("输出类型错误")

        if output.published:
            logger.info("发布成功: %s", output.post_url or "已发布")
            return ValidationResult.success(f"发布成功: {output.post_url or '已发布'}")

        logger.warning("发布失败: %s", output.error_message)
        return ValidationResult.failure(f"发布失败: {output.error_message}")

    def _check_video(self, video_path: Path) -> None:
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        size_mb = video_path.stat().st_size / (1024 * 1024)
        logger.info(f"视频文件: {video_path.name} ({size_mb:.1f} MB)")

    def build_prompt(self, content: XHSVideoContent, video_path: Path) -> str:
        full_body = content.body
        if content.call_to_action:
            full_body = f"{full_body}\n\n{content.call_to_action}"

        # 话题通过"# 话题"按钮单独添加，不拼接到正文中
        hashtags_str = "\n".join([f"   - {tag}" for tag in content.hashtags]) if content.hashtags else "无"

        return publisher_user_prompt(
            title=content.title,
            body=full_body,
            hashtags=hashtags_str,
            video_path=str(video_path.absolute()),
        )
