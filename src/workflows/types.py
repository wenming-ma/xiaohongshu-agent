"""Workflow types and context."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.schemas import ImageResult, PublishResult, ResearchResult, XHSContent, GeneratedImage


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

    # 并行化中间状态：detail 图生成结果（不依赖 content）
    _detail_images: list[GeneratedImage] = field(default_factory=list)
    _image_types: list[dict[str, Any]] = field(default_factory=list)

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
