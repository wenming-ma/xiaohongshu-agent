from typing import List

from pydantic_ai import Agent

from .....core.base_validator import InternalValidator, InternalValidationResult
from ..schemas import VideoResearchResult, VideoSource, Platform
from .....utils.text_model_selector import get_text_model
from .....utils.logger import get_logger
from .prompts import video_quality_system_prompt, video_quality_user_prompt

logger = get_logger(__name__)


class VideoSearchValidator(InternalValidator):

    def __init__(self, min_videos: int = 3, required_platforms: List[Platform] | None = None):
        self.min_videos = min_videos
        self.required_platforms = required_platforms or []

    @property
    def validator_name(self) -> str:
        return "VideoSearch"

    async def validate(self, result: VideoResearchResult, context: dict) -> InternalValidationResult:
        issues = []
        score = 100.0

        if not result.sources:
            return InternalValidationResult(
                passed=False,
                feedback="搜索结果为空，未找到任何视频",
                score=0.0,
            )

        if len(result.sources) < self.min_videos:
            issues.append(f"视频数量不足: {len(result.sources)} < {self.min_videos}")
            score -= 20

        found_platforms = {s.platform for s in result.sources}
        missing = set(self.required_platforms) - found_platforms
        if missing:
            missing_names = ", ".join(p.value for p in missing)
            issues.append(f"缺少平台覆盖: {missing_names}")
            score -= 15 * len(missing)

        for src in result.sources:
            if not src.url or not src.url.startswith("http"):
                issues.append(f"无效 URL: {src.url}")
                score -= 10

        passed = len(result.sources) >= self.min_videos and score >= 70

        if passed:
            feedback = ""
        else:
            feedback = (
                f"**视频搜索验证未通过**\n\n"
                f"当前: {len(result.sources)} 个视频，需要 >= {self.min_videos}\n"
            )
            for issue in issues:
                feedback += f"- {issue}\n"
            feedback += "\n请继续搜索更多视频。"

        validation_result = InternalValidationResult(passed=passed, feedback=feedback, score=max(0, score))
        self._log_result(validation_result)
        return validation_result


class VideoQualityValidator(InternalValidator):
    """视频质量深度验证器 - 在下载前评估视频质量"""

    def __init__(self, pass_score: float = 70.0):
        self.pass_score = pass_score
        self.quality_agent: Agent | None = None

    @property
    def validator_name(self) -> str:
        return "VideoQuality"

    def _init_agent(self) -> None:
        if self.quality_agent is None:
            model = get_text_model()
            self.quality_agent = Agent(
                model=model,
                system_prompt=video_quality_system_prompt(),
            )

    async def validate(self, video: VideoSource, context: dict) -> InternalValidationResult:
        self._init_agent()

        topic = context.get("topic", "未知")

        prompt = video_quality_user_prompt(
            topic=topic,
            platform=video.platform.value,
            url=video.url,
            title=video.title or "无标题",
            description=video.description or "无描述",
            author=video.author or "未知",
            duration=video.duration_seconds or 0,
            likes=video.engagement.likes,
            comments=video.engagement.comments,
            shares=video.engagement.shares,
        )

        try:
            result = await self.quality_agent.run(prompt)
            response_text = result.output

            score = self._extract_score(response_text)
            passed = score >= self.pass_score

            if passed:
                feedback = f"✅ 质量评分: {score}/100 - 通过"
            else:
                feedback = f"❌ 质量评分: {score}/100 - 未通过\n\n{response_text}"

            logger.info(f"视频质量评估: {video.title[:30]}... - 评分: {score}/100 - {'通过' if passed else '未通过'}")

            validation_result = InternalValidationResult(
                passed=passed,
                feedback=feedback,
                score=score,
            )
            self._log_result(validation_result)
            return validation_result

        except Exception as e:
            logger.error(f"视频质量评估失败: {e}")
            return InternalValidationResult(
                passed=False,
                feedback=f"质量评估失败: {str(e)}",
                score=0.0,
            )

    def _extract_score(self, text: str) -> float:
        import re

        score_patterns = [
            r"总分[：:]\s*(\d+)",
            r"得分[：:]\s*(\d+)",
            r"评分[：:]\s*(\d+)",
            r"(\d+)\s*分",
            r"(\d+)/100",
        ]

        for pattern in score_patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))

        lines = text.split("\n")
        for line in lines:
            if "总分" in line or "得分" in line or "评分" in line:
                numbers = re.findall(r"\d+", line)
                if numbers:
                    return float(numbers[0])

        logger.warning("未能从响应中提取评分，默认50分")
        return 50.0


class VideoListQualityFilter:
    """视频列表质量过滤器 - 批量评估并过滤低质量视频"""

    def __init__(self, pass_score: float = 70.0, min_quality_videos: int = 3):
        self.validator = VideoQualityValidator(pass_score=pass_score)
        self.min_quality_videos = min_quality_videos

    async def filter_videos(
        self,
        videos: List[VideoSource],
        topic: str,
        max_videos: int = 5,
    ) -> tuple[List[VideoSource], List[str]]:
        """
        过滤视频列表，只保留高质量视频

        Returns:
            (high_quality_videos, feedback_messages)
        """
        logger.info(f"开始质量评估: {len(videos)} 个视频")

        high_quality_videos = []
        low_quality_videos = []
        feedback_messages = []

        for i, video in enumerate(videos):
            logger.info(f"评估视频 [{i + 1}/{len(videos)}]: {video.title[:50]}...")

            validation = await self.validator.validate(
                video,
                context={"topic": topic}
            )

            if validation.passed:
                high_quality_videos.append(video)
                logger.info(f"  ✅ 通过 - 评分: {validation.score}/100")
            else:
                low_quality_videos.append(video)
                logger.warning(f"  ❌ 未通过 - 评分: {validation.score}/100")
                feedback_messages.append(
                    f"过滤掉低质量视频: {video.title[:50]} (评分: {validation.score}/100)"
                )

            if len(high_quality_videos) >= max_videos:
                logger.info(f"已找到足够的高质量视频 ({max_videos} 个)，停止评估")
                break

        logger.info(f"质量过滤完成: {len(high_quality_videos)} 个通过，{len(low_quality_videos)} 个被过滤")

        return high_quality_videos, feedback_messages
