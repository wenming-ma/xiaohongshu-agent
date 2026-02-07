import logfire
from pathlib import Path
from typing import Any, List

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio

from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoResearchResult, Platform
from .....utils.anthropic_provider import get_anthropic_model
from .....utils.logger import get_logger
from .....config.settings import RetryConfig, PathConfig, TimeoutConfig

from .validator import VideoSearchValidator
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
        pass

    def init_agent(self) -> None:
        model = get_anthropic_model()
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

        logger.info(f"开始视频搜索: {topic}")
        logger.info(f"目标平台: {[p.value for p in platforms]}")

        with logfire.span('video_research:workflow', topic=topic):
            async with self.mcp_server:
                for iteration in range(self.max_iterations):
                    with logfire.span('video_research:iteration', iteration=iteration + 1):
                        await self.step(state, iteration)

                        validation = await self.validate(state.current_result)
                        if validation.passed:
                            logger.info("视频搜索验证通过")
                            return state.current_result

                        self.on_validation_failed(state, iteration, validation.feedback)

                logger.warning(f"达到最大迭代次数 ({self.max_iterations})")
                return state.current_result

    async def step(self, state: ResearchState, iteration: int) -> None:
        logger.info(f"第 {iteration + 1}/{self.max_iterations} 轮搜索")

        if iteration == 0:
            platforms_str = ", ".join(p.value for p in state.platforms)
            prompt = research_user_prompt(
                topic=state.topic,
                platforms=platforms_str,
                max_videos=state.max_videos,
            )
            result = await self.generator.run(prompt)
        else:
            result = await self.generator.run(message_history=state.message_history)

        state.current_result = result.output
        state.message_history = list(result.all_messages())

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, VideoResearchResult):
            return ValidationResult.failure("结果类型错误")

        if not output.sources:
            return ValidationResult.failure("未找到任何视频源")

        validator_result = await self.search_validator.validate(
            output, {"min_videos": self.search_validator.min_videos}
        )

        if validator_result.passed:
            return ValidationResult.success("视频搜索验证通过")
        return ValidationResult.failure(validator_result.feedback)

    def on_validation_failed(self, state: ResearchState, iteration: int, feedback: str) -> None:
        logger.warning("搜索验证未通过，注入反馈继续...")
        state.inject_feedback(feedback)
