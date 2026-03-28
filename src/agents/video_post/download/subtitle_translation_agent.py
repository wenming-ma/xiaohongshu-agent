from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ....config.settings import ReviewConfig, RetryConfig
from ....core.base_agent import BaseAgent, ValidationResult
from ....utils.logger import get_logger
from ....utils.providers import get_text_model
from ..utils.tts_tags import DEFAULT_TONE_TAG, normalize_tone_tag
from .prompts import (
    download_subtitle_review_system_prompt,
    download_subtitle_review_user_prompt,
    download_subtitle_revision_user_prompt,
    download_subtitle_translation_system_prompt,
    download_subtitle_translation_user_prompt,
)
from .subtitle import SubtitleSegment, _normalize_subtitle_text

logger = get_logger(__name__)

_LANG_NAMES = {
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "fr": "法文",
    "es": "西班牙文",
    "de": "德文",
    "pt": "葡萄牙文",
    "ru": "俄文",
    "th": "泰文",
    "vi": "越南文",
    "ar": "阿拉伯文",
    "it": "意大利文",
    "mixed": "混合语言",
    "zh": "中文字幕",
}


class TranslationLine(BaseModel):
    index: int = Field(ge=1)
    tone_tag: str = DEFAULT_TONE_TAG
    text: str = ""


class TranslationBatch(BaseModel):
    lines: list[TranslationLine]


class SubtitleTranslationReview(BaseModel):
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    summary: str = ""


@dataclass
class SubtitleTranslationState:
    source_segments: list[SubtitleSegment]
    source_language: str
    translate_first: bool
    current_segments: list[SubtitleSegment] = field(default_factory=list)
    current_review: SubtitleTranslationReview | None = None
    last_feedback: str = ""

    def inject_feedback(self, feedback: str) -> None:
        self.last_feedback = feedback.strip()


class SubtitleTranslationAgent(BaseAgent):

    role = "字幕翻译审核专员"
    goal = "输出通过审核、适合中文 TTS 的字幕"

    def __init__(
        self,
        max_review_rounds: int | None = None,
    ):
        self.max_review_rounds = max_review_rounds or ReviewConfig.MAX_ITERATIONS
        self._state_var: ContextVar[SubtitleTranslationState | None] = ContextVar(
            "subtitle_translation_state",
            default=None,
        )
        super().__init__()

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        model = get_text_model()
        self.translator = Agent(
            model=model,
            output_type=TranslationBatch,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(download_subtitle_translation_system_prompt(),),
        )
        self.reviewer = Agent(
            model=model,
            output_type=SubtitleTranslationReview,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(download_subtitle_review_system_prompt(),),
        )

    async def forward(
        self,
        segments: list[SubtitleSegment],
        *,
        source_language: str,
        translate_first: bool = True,
    ) -> list[SubtitleSegment]:
        normalized_source = [self._normalize_segment(segment) for segment in segments]
        if not normalized_source:
            return []

        state = SubtitleTranslationState(
            source_segments=normalized_source,
            source_language=source_language or "mixed",
            translate_first=translate_first,
            current_segments=[],
        )
        if not translate_first:
            state.current_segments = [self._normalize_segment(segment) for segment in normalized_source]

        token = self._state_var.set(state)
        try:
            for review_round in range(self.max_review_rounds):
                if review_round == 0:
                    if state.translate_first:
                        await self.step(state, review_round)
                else:
                    await self.step(state, review_round)

                validation = await self.validate(state.current_segments)
                if validation.passed:
                    logger.info(f"字幕翻译审核通过 (第{review_round + 1}轮)")
                    return [self._normalize_segment(segment) for segment in state.current_segments]

                self.on_validation_failed(state, review_round, validation.feedback)

            review = state.current_review or SubtitleTranslationReview()
            raise RuntimeError(
                f"字幕翻译审核未通过，达到最大审核轮数 ({self.max_review_rounds}): "
                f"{self._build_translation_review_feedback(review)}"
            )
        finally:
            self._state_var.reset(token)

    async def step(self, state: SubtitleTranslationState, iteration: int) -> list[SubtitleSegment]:
        mode = "translate" if iteration == 0 and state.translate_first else "revise"
        prompt = self._build_step_prompt(state, mode)
        result = await self.translator.run(prompt)
        fallback_segments = state.current_segments or state.source_segments
        state.current_segments = self._build_segments_from_result(
            source_segments=state.source_segments,
            translation_batch=result.output,
            fallback_segments=fallback_segments,
        )
        return state.current_segments

    async def validate(self, output: Any) -> ValidationResult:
        state = self._state_var.get()
        if state is None:
            return ValidationResult.failure("字幕翻译状态缺失")
        if not isinstance(output, list):
            return ValidationResult.failure("字幕翻译输出类型错误")

        prompt = self._build_review_prompt(
            source_segments=state.source_segments,
            translated_segments=state.current_segments,
            source_language=state.source_language,
        )
        result = await self.reviewer.run(prompt)
        state.current_review = result.output

        if state.current_review.passed:
            return ValidationResult.success(state.current_review.summary or "字幕审核通过")

        return ValidationResult.failure(self._build_translation_review_feedback(state.current_review))

    def on_validation_failed(
        self,
        state: SubtitleTranslationState,
        iteration: int,
        feedback: str,
    ) -> None:
        state.inject_feedback(feedback)
        summary = ""
        if state.current_review is not None:
            summary = state.current_review.summary or feedback
        logger.warning(f"字幕翻译审核未通过 (第{iteration + 1}轮): {summary or feedback}")

    def _build_step_prompt(self, state: SubtitleTranslationState, mode: str) -> str:
        source_lines, speaker_instruction = self._format_segments(state.source_segments)
        if mode == "translate":
            return download_subtitle_translation_user_prompt(
                lang_name=self._resolve_lang_name(state.source_language),
                source_lines=source_lines,
                speaker_instruction=speaker_instruction,
            )

        current_lines, _ = self._format_segments(state.current_segments)
        return download_subtitle_revision_user_prompt(
            lang_name=self._resolve_lang_name(state.source_language),
            feedback=state.last_feedback or "请修复所有非中文和不自然表达。",
            source_lines=source_lines,
            current_lines=current_lines,
            speaker_instruction=speaker_instruction,
        )

    def _build_review_prompt(
        self,
        *,
        source_segments: list[SubtitleSegment],
        translated_segments: list[SubtitleSegment],
        source_language: str,
    ) -> str:
        source_lines, _ = self._format_segments(source_segments)
        translated_lines, _ = self._format_segments(translated_segments)
        return download_subtitle_review_user_prompt(
            lang_name=self._resolve_lang_name(source_language),
            source_lines=source_lines,
            translated_lines=translated_lines,
        )

    def _build_segments_from_result(
        self,
        *,
        source_segments: list[SubtitleSegment],
        translation_batch: TranslationBatch,
        fallback_segments: list[SubtitleSegment],
    ) -> list[SubtitleSegment]:
        translated_lines = {line.index: line for line in translation_batch.lines}
        translated_segments: list[SubtitleSegment] = []

        for line_index, segment in enumerate(source_segments, start=1):
            translated_line = translated_lines.get(line_index)
            fallback_segment = (
                fallback_segments[line_index - 1]
                if line_index - 1 < len(fallback_segments)
                else segment
            )
            translated_text = (
                _normalize_subtitle_text(translated_line.text)
                if translated_line is not None
                else ""
            )
            if not translated_text:
                translated_text = _normalize_subtitle_text(fallback_segment.text)

            tone_source = translated_line.tone_tag if translated_line is not None else fallback_segment.tone_tag
            translated_segments.append(
                SubtitleSegment(
                    start=segment.start,
                    end=segment.end,
                    text=translated_text,
                    speaker_id=segment.speaker_id,
                    tone_tag=normalize_tone_tag(tone_source or DEFAULT_TONE_TAG),
                )
            )

        return translated_segments

    @staticmethod
    def _format_segments(segments: list[SubtitleSegment]) -> tuple[str, str]:
        has_multiple_speakers = len({segment.speaker_id for segment in segments}) > 1
        if has_multiple_speakers:
            lines = "\n".join(
                f"{index + 1}. [说话人{segment.speaker_id}] {segment.text}"
                for index, segment in enumerate(segments)
            )
            speaker_instruction = (
                "- 每行开头的 [说话人N] 只是上下文，不要出现在输出里\n"
                "- 说话人不同可以保留不同语气\n"
            )
            return lines, speaker_instruction

        lines = "\n".join(
            f"{index + 1}. {segment.text}"
            for index, segment in enumerate(segments)
        )
        return lines, ""

    @staticmethod
    def _build_translation_review_feedback(review: SubtitleTranslationReview) -> str:
        lines = [review.summary.strip() or "字幕中文审核未通过，请根据问题修订。"]
        for issue in review.issues:
            cleaned = issue.strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_segment(segment: SubtitleSegment) -> SubtitleSegment:
        return SubtitleSegment(
            start=segment.start,
            end=segment.end,
            text=_normalize_subtitle_text(segment.text),
            speaker_id=segment.speaker_id,
            tone_tag=normalize_tone_tag(segment.tone_tag or DEFAULT_TONE_TAG),
        )

    @staticmethod
    def _resolve_lang_name(source_language: str) -> str:
        return _LANG_NAMES.get(source_language or "mixed", f"{source_language} 字幕")
