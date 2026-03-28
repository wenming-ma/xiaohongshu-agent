import logfire
from pathlib import Path
from typing import Any, List

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.usage import UsageLimits

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoResearchResult, VideoSource, Platform
from ....utils.providers import get_text_model
from ....utils.logger import get_logger
from ....config.settings import RetryConfig, PathConfig
from ...shared import create_shared_playwright_mcp_server

from .validator import VideoSearchValidator, VideoListQualityFilter
from .prompts import research_system_prompt, research_user_prompt
from .state import ResearchState

logger = get_logger(__name__)

MAX_ITERATIONS = 10
MAX_HISTORY_ROUNDS = 3


class ResearchAgent(BaseAgent):

    role = "跨平台视频研究员"
    goal = "在 X/Instagram/Facebook/TikTok 搜索高质量视频"

    def __init__(self):
        self.init_mcp_server()
        super().__init__()
        self.init_validators()

    def init_mcp_server(self) -> None:
        self.mcp_server = create_shared_playwright_mcp_server(
            output_dir=PathConfig.DOWNLOADS_DIR,
            tool_prefix='playwright',
            headless=False,
        )

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
        self.search_validator = VideoSearchValidator(min_videos=5)
        self.quality_filter = VideoListQualityFilter(pass_score=70.0, min_quality_videos=15)
        self.max_iterations = MAX_ITERATIONS
        self._accumulated_quality_videos: list[VideoSource] = []
        self._filtered_sources: list[VideoSource] | None = None

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

        self._accumulated_quality_videos = []

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

                        self._filtered_sources = None
                        validation = await self.validate(state.current_result)
                        if validation.passed:
                            if self._filtered_sources is not None:
                                state.current_result.sources = self._filtered_sources
                            logger.info("Search and quality review passed")
                            return state.current_result

                        self.on_validation_failed(state, iteration, validation.feedback)

                logger.warning(f"Max iterations reached ({self.max_iterations})")
                return state.current_result

    async def step(self, state: ResearchState, iteration: int) -> None:
        recent_history = state.get_recent_history(MAX_HISTORY_ROUNDS)
        if iteration == 0:
            platforms_str = ", ".join(p.value for p in state.platforms)
            prompt = research_user_prompt(
                topic=state.topic,
                platforms=platforms_str,
                max_videos=state.max_videos,
            )
            logger.info("AI agent searching...")
        else:
            logger.info("AI agent continuing with feedback...")
            prompt = state.last_feedback or "请基于上轮结果继续扩展并优化搜索结果。"

        try:
            result = await self.generator.run(
                prompt,
                message_history=recent_history,
                usage_limits=UsageLimits(request_limit=None),
            )
        except ModelHTTPError as e:
            error_text = str(e).lower()
            if "tool call id is invalid" not in error_text:
                raise
            logger.warning(
                "检测到 tool call id 失效，已清空历史并在当前轮次重试一次。"
            )
            state.message_history.clear()
            result = await self.generator.run(
                prompt,
                usage_limits=UsageLimits(request_limit=None),
            )

        state.current_result = result.output
        state.record_result(state.current_result)
        state.message_history.extend(result.new_messages())
        logger.info(f"Found {len(state.current_result.sources)} videos")

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, VideoResearchResult):
            return ValidationResult.failure("结果类型错误")

        if not output.sources:
            return ValidationResult.failure("未找到任何视频源")

        # 基础验证：数量和URL（仅对当前轮）
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

        # 合并本轮通过的视频到累积池（按 URL 去重）
        seen_urls = {v.url for v in self._accumulated_quality_videos}
        for v in quality_videos:
            if v.url not in seen_urls:
                self._accumulated_quality_videos.append(v)
                seen_urls.add(v.url)

        total_quality = len(self._accumulated_quality_videos)
        logger.info(f"累计高质量视频: {total_quality} 个（本轮新增 {len(quality_videos)} 个）")

        if total_quality >= self.quality_filter.min_quality_videos:
            self._filtered_sources = self._accumulated_quality_videos
            logger.info(f"质量审核通过: {total_quality} 个高质量视频")
            return ValidationResult.success(f"找到 {total_quality} 个高质量视频")
        else:
            quality_feedback = (
                f"质量审核未通过: 累计 {total_quality} 个视频通过质量检测，"
                f"需要至少 {self.quality_filter.min_quality_videos} 个。\n\n"
                f"建议:\n"
                f"1. 搜索更多不同的视频（避免重复已搜索过的）\n"
                f"2. 尝试不同的搜索关键词\n"
                f"3. 寻找教程、经验分享、深度探店类视频\n\n"
                f"过滤原因:\n" + "\n".join(feedback_msgs)
            )
            return ValidationResult.failure(quality_feedback)

    def on_validation_failed(self, state: ResearchState, iteration: int, feedback: str) -> None:
        logger.warning("搜索验证未通过，注入反馈继续...")
        state.inject_feedback(feedback)
