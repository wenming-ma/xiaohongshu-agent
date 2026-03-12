import logfire
from pathlib import Path
from typing import Any, List

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio

from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoResearchResult, Platform
from .....utils.providers import get_text_model
from .....utils.logger import get_logger
from .....utils.playwright_artifacts import install_playwright_artifact_guard
from .....config.settings import RetryConfig, PathConfig, TimeoutConfig

from .validator import VideoSearchValidator, VideoListQualityFilter
from .prompts import research_system_prompt, research_user_prompt
from .state import ResearchState

logger = get_logger(__name__)

MAX_ITERATIONS = 5


class ResearchAgent(BaseAgent):

    role = "跨平台视频研究员"
    goal = "在 X/Instagram/Facebook/TikTok 搜索高质量视频"

    def __init__(self):
        self.init_mcp_server()
        super().__init__()
        self.init_validators()

    def init_mcp_server(self) -> None:
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=[
                '-y', '@playwright/mcp@latest',
                '--browser', 'chromium',
                '--user-data-dir', PathConfig.BROWSER_SESSION_SHARED,
                '--output-dir', str(PathConfig.DOWNLOADS_DIR),
            ],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_SHARED,
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )
        install_playwright_artifact_guard(self.mcp_server)

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        model = get_text_model()
        self.generator = Agent(
            model=model,
            output_type=VideoResearchResult,
            toolsets=[self.mcp_server],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(research_system_prompt(),),
        )

    def init_validators(self) -> None:
        self.search_validator = VideoSearchValidator(min_videos=3)
        self.quality_filter = VideoListQualityFilter(pass_score=70.0, min_quality_videos=3)
        self.max_iterations = MAX_ITERATIONS

    async def forward(
        self,
        topic: str,
        platforms: List[Platform],
        max_videos: int = 5,
        output_dir: Path | None = None,
    ) -> VideoResearchResult:
        state = ResearchState(
            topic=topic,
            platforms=platforms,
            max_videos=max_videos,
            output_dir=output_dir,
        )

        logger.info(f"Starting video search: {topic}")
        logger.info(f"Platforms: {[p.value for p in platforms]}")
        logger.info("Initializing Playwright MCP server...")

        with logfire.span('video_research:workflow', topic=topic):
            async with self.mcp_server:
                logger.info("MCP server ready, starting search...")

                for iteration in range(self.max_iterations):
                    logger.info(f"Search iteration {iteration + 1}/{self.max_iterations}")

                    with logfire.span('video_research:iteration', iteration=iteration + 1):
                        await self.step(state, iteration)

                        validation = await self.validate(state.current_result)
                        if validation.passed:
                            logger.info("Search and quality review passed")
                            return state.current_result

                        self.on_validation_failed(state, iteration, validation.feedback)

                logger.warning(f"Max iterations reached ({self.max_iterations})")
                return state.current_result

    async def step(self, state: ResearchState, iteration: int) -> None:
        if iteration == 0:
            platforms_str = ", ".join(p.value for p in state.platforms)
            prompt = research_user_prompt(
                topic=state.topic,
                platforms=platforms_str,
                max_videos=state.max_videos,
            )
            logger.info("AI agent searching...")
            result = await self.generator.run(prompt)
        else:
            logger.info("AI agent continuing with feedback...")
            result = await self.generator.run(message_history=state.message_history)

        state.current_result = result.output
        state.message_history = list(result.all_messages())
        logger.info(f"Found {len(state.current_result.sources)} videos")

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, VideoResearchResult):
            return ValidationResult.failure("结果类型错误")

        if not output.sources:
            return ValidationResult.failure("未找到任何视频源")

        # 基础验证：数量和URL
        validator_result = await self.search_validator.validate(
            output, {"min_videos": self.search_validator.min_videos}
        )

        if not validator_result.passed:
            return ValidationResult.failure(validator_result.feedback)

        # 质量深度审核
        logger.info("基础验证通过，开始质量深度审核...")

        quality_videos, feedback_msgs = await self.quality_filter.filter_videos(
            videos=output.sources,
            topic=output.topic,
            max_videos=len(output.sources),
        )

        if len(quality_videos) >= self.quality_filter.min_quality_videos:
            # 更新结果，只保留高质量视频
            output.sources = quality_videos
            logger.info(f"质量审核通过: {len(quality_videos)} 个高质量视频")
            return ValidationResult.success(f"找到 {len(quality_videos)} 个高质量视频")
        else:
            quality_feedback = (
                f"质量审核未通过: 仅 {len(quality_videos)} 个视频通过质量检测，"
                f"需要至少 {self.quality_filter.min_quality_videos} 个。\n\n"
                f"建议:\n"
                f"1. 搜索更多视频（目标: 有完整故事、有深度的内容）\n"
                f"2. 避免随意拍摄的 TikTok 娱乐片段\n"
                f"3. 寻找教程、经验分享、深度探店类视频\n\n"
                f"过滤原因:\n" + "\n".join(feedback_msgs)
            )
            return ValidationResult.failure(quality_feedback)

    def on_validation_failed(self, state: ResearchState, iteration: int, feedback: str) -> None:
        logger.warning("搜索验证未通过，注入反馈继续...")
        state.inject_feedback(feedback)
