from typing import List

from .....core.base_validator import InternalValidator, InternalValidationResult
from ..schemas import VideoResearchResult, ContentReviewResult, Platform
from .....utils.logger import get_logger

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
