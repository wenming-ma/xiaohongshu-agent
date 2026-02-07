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
        self.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=feedback)])
        )
