"""Workflow types and context."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..models.schemas import ImageResult, PublishResult, ResearchResult, XHSContent


@dataclass
class WorkflowContext:
    topic: str
    audience: str
    output_dir: Path
    generate_image: bool = True
    publish: bool = True
    research: ResearchResult | None = None
    content: XHSContent | None = None
    image_result: ImageResult | None = None
    publish_result: PublishResult | None = None

    @classmethod
    def create(
        cls,
        *,
        topic: str,
        audience: str,
        generate_image: bool = True,
        publish: bool = True,
        output_root: Path | None = None,
    ) -> "WorkflowContext":
        base_dir = output_root or Path("posts")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_topic = "".join(c for c in topic if c.isalnum() or c in (" ", "-", "_"))[:20]
        output_dir = base_dir / f"{timestamp}-{safe_topic}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            topic=topic,
            audience=audience,
            output_dir=output_dir,
            generate_image=generate_image,
            publish=publish,
        )
