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

    def inject_feedback(self, feedback: str) -> None:
        # Enhance feedback with exploration guidance
        enhanced_feedback = f"""{feedback}

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
        self.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=enhanced_feedback)])
        )
