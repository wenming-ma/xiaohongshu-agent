import re
from typing import Any

from pydantic_ai import Agent

from ....core.base_agent import BaseAgent, ValidationResult
from ..schemas import VideoResearchResult, VideoSource, XHSVideoContent, ContentReviewResult, TranscriptionResult
from ....utils.providers import get_text_model
from ....utils.logger import get_logger
from ....config.settings import RetryConfig, ReviewConfig

from .prompts import (
    content_revision_user_prompt,
    content_system_prompt,
    content_user_prompt,
    content_review_system_prompt,
    content_review_user_prompt,
)
from .state import ContentState

logger = get_logger(__name__)

MAX_HISTORY_ROUNDS = 3
AI_TEMPLATE_PHRASE_RE = re.compile(
    r"(首先|其次|再次|接下来|最后|总的来说|综上所述|总而言之|值得注意的是|需要指出的是|不可否认|从某种程度上来说|本质上|其核心在于)"
)


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
            model=get_text_model(),
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
        self._current_state = state

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
            prompt = content_revision_user_prompt(
                topic=state.topic,
                feedback=state.last_feedback or "请根据审核反馈修订内容。",
            )

        recent_history = state.get_recent_history(MAX_HISTORY_ROUNDS)
        run_result = await self.generator.run(prompt, message_history=recent_history)
        state.current_content = run_result.output
        state.message_history.extend(run_result.new_messages())
        self._current_state = state

    def _mechanical_check(self, content: XHSVideoContent) -> tuple[float, list[str]]:
        """确定性规则检查，返回 (扣分, 问题列表)"""
        deductions = 0.0
        issues = []

        title_len = len(content.title)
        if title_len < 10 or title_len > 30:
            deductions += 20
            issues.append(f"标题长度不合规: {title_len} 字（需 10-30）")

        body_len = len(content.body)
        if body_len < 50:
            deductions += 20
            issues.append(f"正文太短: {body_len} 字（需 >= 50）")

        if len(content.hashtags) > 5:
            deductions += 10
            issues.append(f"标签过多: {len(content.hashtags)} 个（最多 5）")

        if re.search(r"\*\*[^*]+\*\*|\*[^*]+\*|^#{1,6}\s|^\s*[-*]\s", content.body, re.MULTILINE):
            deductions += 10
            issues.append("正文包含 Markdown 格式")

        if not content.call_to_action:
            has_cta = bool(re.search(r"[？?]|评论|留言|分享|关注|点赞|收藏", content.body))
            if not has_cta:
                deductions += 10
                issues.append("缺少互动引导")

        template_hits = AI_TEMPLATE_PHRASE_RE.findall(content.body)
        if template_hits:
            unique_hits = []
            for hit in template_hits:
                if hit not in unique_hits:
                    unique_hits.append(hit)
            if len(template_hits) >= 2:
                deductions += 15
                issues.append(f"正文模板化衔接词过多: {', '.join(unique_hits)}")
            else:
                deductions += 8
                issues.append(f"正文存在明显 AI 模板词: {unique_hits[0]}")

        return deductions, issues

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, XHSVideoContent):
            return ValidationResult.failure("输出类型错误")

        if not output.title or not output.body:
            return ValidationResult.failure("缺少标题或正文")

        # 先做确定性规则检查，不过就直接返回，不浪费 LLM 调用
        deductions, mech_issues = self._mechanical_check(output)
        if deductions >= 30:
            score = max(0, 100 - deductions)
            feedback = (
                f"内容基础检查未通过。\n"
                f"评分: {score:.1f}/100\n"
            )
            for issue in mech_issues:
                feedback += f"- {issue}\n"
            logger.warning(f"基础检查未通过（扣 {deductions} 分），跳过 LLM 审核")

            state = self._current_state
            state.current_review = ContentReviewResult(
                passed=False, score=score, issues=mech_issues,
                summary="基础规范检查未通过",
            )
            return ValidationResult.failure(feedback)

        # 基础检查通过，调用 LLM 做 AI 痕迹检测
        state = self._current_state
        review_prompt = content_review_user_prompt(
            content=output.model_dump_json(indent=2),
        )
        review_result = await self.reviewer.run(
            review_prompt,
            message_history=state.get_recent_review_history(MAX_HISTORY_ROUNDS),
        )
        state.current_review = review_result.output
        state.review_history.extend(review_result.new_messages())

        # 将机械扣分叠加到 LLM 评分上
        if mech_issues:
            state.current_review.score = max(0, state.current_review.score - deductions)
            state.current_review.issues = mech_issues + state.current_review.issues
            state.current_review.passed = state.current_review.score >= 70

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
