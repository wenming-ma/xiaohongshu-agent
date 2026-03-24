from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from ..schemas import VideoResearchResult, Platform


@dataclass
class ResearchState:
    topic: str
    platforms: List[Platform]
    max_videos: int
    output_dir: Path | None

    message_history: list[ModelMessage] = field(default_factory=list)
    current_result: VideoResearchResult | None = None
    last_feedback: str | None = None

    def inject_feedback(self, feedback: str) -> None:
        # Store revision feedback as prompt text for next iteration.
        self.last_feedback = f"""{feedback}

### Next Actions Required
1. Scroll down MORE on each platform (at least 5 more scrolls)
2. Try these alternative keyword variations:
   - "{self.topic} tutorial"
   - "{self.topic} vlog"
   - "{self.topic} review"
3. Click into video details you haven't visited yet
4. Check other platform sections (Trending, Explore, etc.)

IMPORTANT: Use natural browsing behavior, not direct search URLs!
"""
        self.last_feedback = self.last_feedback.strip()

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        """保留首轮（含 SystemPrompt + 首条用户消息）+ 最近 N-1 轮"""
        history = self.message_history
        if not history or max_rounds <= 0:
            return []

        run_boundaries = [
            idx
            for idx, msg in enumerate(history)
            if isinstance(msg, ModelRequest)
            and any(isinstance(part, UserPromptPart) for part in msg.parts)
        ]

        if len(run_boundaries) <= max_rounds:
            return history

        # 首轮结束位置 = 第二轮开始位置
        first_round_end = run_boundaries[1] if len(run_boundaries) > 1 else len(history)
        if max_rounds <= 1:
            return history[:first_round_end]

        recent_start = run_boundaries[-(max_rounds - 1)]
        return history[:first_round_end] + history[recent_start:]
