from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest

from .....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoResearchResult, VideoSource, XHSVideoContent, ContentReviewResult, TranscriptionResult
from .....utils.text_model_selector import get_text_model
from .....utils.review_provider import get_review_model
from .....utils.logger import get_logger
from .....config.settings import RetryConfig, ReviewConfig

from .prompts import (
    content_system_prompt,
    content_user_prompt,
    content_review_system_prompt,
    content_review_user_prompt,
)
from .state import ContentState

logger = get_logger(__name__)

MAX_HISTORY_ROUNDS = 3


def _safe_history_slice(history: list[ModelMessage], max_rounds: int) -> list[ModelMessage]:
    if len(history) <= max_rounds * 2:
        return history
    boundaries = [i for i, msg in enumerate(history) if isinstance(msg, ModelRequest)]
    if len(boundaries) <= max_rounds:
        return history
    start = boundaries[-max_rounds]
    return history[start:]


class ContentAgent(BaseAgent):

    role = "视频内容适配师"
    goal = "将海外视频信息转化为小红书风格内容"

    def __init__(self, max_iterations: int = None):
        self.max_iterations = max_iterations or ReviewConfig.MAX_ITERATIONS
        super().__init__()

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        model = get_text_model()
        self.generator = Agent(
            model=model,
            output_type=XHSVideoContent,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(content_system_prompt(),),
        )

        self.reviewer = Agent(
            model=get_review_model(),
            output_type=ContentReviewResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(content_review_system_prompt(),),
        )

    async def forward(
        self,
        research: VideoResearchResult,
        video_source: VideoSource,
        topic: str,
        transcript: TranscriptionResult | None = None,
    ) -> XHSVideoContent:
        state = ContentState(research=research, video_source=video_source, topic=topic, transcript=transcript)

        logger.info(f"开始生成视频内容: {topic}")

        for iteration in range(self.max_iterations):
            await self.step(state, iteration)

            validation = await self.validate(state.current_content)
            if validation.passed:
                logger.info(f"内容审核通过 (第{iteration+1}轮)")
                return state.current_content

            self.on_validation_failed(state, iteration, validation.feedback)

        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前内容")
        return state.current_content

    async def step(self, state: ContentState, iteration: int) -> None:
        if iteration == 0:
            engagement_str = (
                f"点赞: {state.video_source.engagement.likes}, "
                f"评论: {state.video_source.engagement.comments}, "
                f"分享: {state.video_source.engagement.shares}"
            )
            transcript_section = ""
            if state.transcript and state.transcript.success and state.transcript.transcript:
                transcript_section = (
                    f"\n**视频转录文本**:\n{state.transcript.transcript}\n"
                )
            prompt = content_user_prompt(
                topic=state.topic,
                platform=state.video_source.platform.value,
                video_title=state.video_source.title,
                video_description=state.video_source.description,
                engagement=engagement_str,
                transcript_section=transcript_section,
                research_summary=state.research.summary,
            )
        else:
            prompt = "请根据反馈修订内容。"

        recent_history = _safe_history_slice(state.message_history, MAX_HISTORY_ROUNDS)
        run_result = await self.generator.run(prompt, message_history=recent_history)
        state.current_content = run_result.output
        state.message_history.extend(run_result.new_messages())
        self._current_state = state

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, XHSVideoContent):
            return ValidationResult.failure("输出类型错误")

        if not output.title or not output.body:
            return ValidationResult.failure("缺少标题或正文")

        state = self._current_state
        review_prompt = content_review_user_prompt(
            content=output.model_dump_json(indent=2),
        )
        review_result = await self.reviewer.run(
            review_prompt,
            message_history=_safe_history_slice(state.review_history, MAX_HISTORY_ROUNDS),
        )
        state.current_review = review_result.output
        state.review_history.extend(review_result.new_messages())

        if state.current_review.passed:
            return ValidationResult.success(f"审核通过，评分: {state.current_review.score:.1f}")

        feedback = (
            f"内容审核未通过。\n"
            f"评分: {state.current_review.score:.1f}/100\n"
            f"反馈: {state.current_review.summary}\n"
        )
        for issue in state.current_review.issues:
            feedback += f"- {issue}\n"
        return ValidationResult.failure(feedback)

    def on_validation_failed(self, state: ContentState, iteration: int, feedback: str) -> None:
        logger.warning(f"内容审核未通过 (第{iteration+1}轮)")
        state.inject_feedback(feedback)
