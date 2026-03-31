"""XHS Styled Image Post Schemas"""

from dataclasses import dataclass, field
from pathlib import Path
from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Dict, Any, TypedDict


class StyledImagePostInput(BaseModel):
    topic: str
    audience: str
    publish: bool = True


class StyledImagePostOutput(BaseModel):
    success: bool
    title: str = ""
    body_preview: str = ""
    hashtags: list[str] = []
    image_count: int = 0
    image_paths: list[str] = []
    published: bool = False
    post_url: str | None = None
    output_dir: str = ""
    error_message: str | None = None


# ============================================================================
# 参考图片收集相关模型
# ============================================================================

class VisualItemDetail(BaseModel):
    """单个需要视觉指定的物品"""
    name: str
    description: str
    visual_questions: list[str]


class GroupVisualAnalysis(BaseModel):
    """单个分组的 LLM 视觉分析结果"""
    group_index: int
    group_title: str
    has_visual_items: bool
    visual_items: list[VisualItemDetail] = []
    summary: str


class ItemReferenceImages(BaseModel):
    """单个物品的参考图片（支持多张，如不同角度）"""
    item_name: str
    image_paths: list[str] = []


class ReferenceImageGroup(BaseModel):
    """单个分组收集到的参考图片（按物品组织）"""
    group_index: int
    group_title: str
    items: list[ItemReferenceImages] = []


class ReferenceImageResult(BaseModel):
    """参考图片收集总结果"""
    groups: list[ReferenceImageGroup] = []
    skipped: bool = False

    def get_images_for_group(self, group_index: int, max_total: int = 0) -> list[Path]:
        """获取该分组所有物品的所有参考图（平铺，可截断）"""
        from ..config.settings import ReferenceImageConfig
        cap = max_total or ReferenceImageConfig.MAX_TOTAL_IMAGES_PER_GROUP
        for g in self.groups:
            if g.group_index == group_index:
                all_paths = [Path(p) for item in g.items for p in item.image_paths]
                if len(all_paths) > cap:
                    import logging
                    logging.getLogger(__name__).warning(
                        "分组 %d 参考图片 %d 张超过上限 %d，截断", group_index, len(all_paths), cap
                    )
                    return all_paths[:cap]
                return all_paths
        return []

    def has_images_for_group(self, group_index: int) -> bool:
        return len(self.get_images_for_group(group_index)) > 0


@dataclass
class ImageGenContext:
    """图片生成上下文（用于依赖注入）"""

    topic: str = ""
    image_type: str = ""
    validation_feedback: str = ""
    reference_item_names: list[str] = field(default_factory=list)


class GroupSpec(TypedDict):
    title: str
    indices: list[int]


class CompactKeyInfo(TypedDict):
    index: int
    type: str | None
    name: str
    text: str


class ImageTypeSpec(TypedDict, total=False):
    type: str
    desc: str
    group_title: str
    indices: list[int]


class ResearchItem(BaseModel):
    title: str
    content: str
    item_type: Optional[str] = None
    source_ref: Optional[str] = None


class ContentSource(BaseModel):
    url: str
    title: str
    domain: str
    likes: Optional[int] = None
    comments: Optional[int] = None


class ResearchResult(BaseModel):
    summary: str
    items: List[ResearchItem] = []
    keywords: List[str] = []
    sources: List[ContentSource] = []

    @computed_field
    @property
    def items_count(self) -> int:
        return len(self.items)

    @computed_field
    @property
    def sources_count(self) -> int:
        return len(self.sources)


class XHSContent(BaseModel):
    title: str = Field(min_length=10, max_length=30)
    body: str = Field(min_length=100)
    hashtags: List[str] = Field(default=[], max_length=5)
    call_to_action: str = ""


class ReviewIssue(BaseModel):
    type: str
    severity: str
    description: str
    suggestion: str


class ReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: List[ReviewIssue] = []
    summary: str
    entity_usage: Optional[Dict[str, Any]] = None


class GeneratedImage(BaseModel):
    image_path: str
    prompt_used: str
    image_type: str


class ImageResult(BaseModel):
    images: List[GeneratedImage] = []
    total_count: int
    generated_at: str


class ImageGroupingGroup(BaseModel):
    title: str
    indices: List[int] = []
    rationale: Optional[str] = None


class ImageGroupingPlan(BaseModel):
    groups: List[ImageGroupingGroup] = []


class ImageGroupingReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: List[str] = []
    summary: str = ""


class ImageQualityReview(BaseModel):
    passed: bool
    text_clarity_score: float = Field(default=0.0, ge=0.0, le=100.0)
    style_score: float = Field(default=0.0, ge=0.0, le=100.0)
    aspect_ratio_correct: bool = True
    text_is_chinese: bool = True
    issues: List[str] = []
    summary: str


class ImageReadResult(BaseModel):
    extracted_text: str = ""
    description: str = ""
    language: str = "unknown"
    has_text: bool = False
    answer: str = ""
    issues: List[str] = []


class PostImageItem(BaseModel):
    """单张帖子图片的分析结果"""
    index: int
    url: str = ""
    extracted_text: str = ""
    description: str = ""
    has_text: bool = False
    issues: List[str] = []


class PostImagesReadResult(BaseModel):
    """帖子所有图片的汇总分析结果"""
    post_type: str = ""
    image_count: int = 0
    images: List[PostImageItem] = []
    issues: List[str] = []


class VideoReadResult(BaseModel):
    """视频语音转文字结果"""
    success: bool = False
    transcript: str = ""
    language: str = "unknown"
    duration_seconds: float = 0.0
    error_message: str = ""


class PublishResult(BaseModel):
    published: bool
    platform: str = "xiaohongshu"
    publish_time: str
    post_url: str = ""
    error_message: str = ""
    retry_count: int = 0
    content_snapshot: Optional[Dict[str, Any]] = None
    image_paths: Optional[List[str]] = None
