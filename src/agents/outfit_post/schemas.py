"""XHS Outfit Post Schemas - 穿搭搭配帖子数据模型"""

from dataclasses import dataclass, field
from pathlib import Path
from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Dict, Any, TypedDict


# ============================================================================
# Outfit Post 专用
# ============================================================================

class OutfitItem(BaseModel):
    """用户定义的穿搭单品"""
    name: str
    description: str = ""


class OutfitItemList(BaseModel):
    """LLM 解析用户文本后的单品列表"""
    items: list[OutfitItem] = []


class StyleOption(BaseModel):
    """单个风格方向选项"""
    label: str  # 简短标签，如 "休闲街头"
    keyword: str  # 用于搜索的关键词，如 "休闲街头穿搭"


class StyleSuggestion(BaseModel):
    """LLM 根据单品推荐的风格方向"""
    options: list[StyleOption] = []  # 3-5 个风格选项


class OutfitPostInput(BaseModel):
    topic: str = ""  # 风格提示，如 "休闲风穿搭"、"通勤穿搭"，可为空
    audience: str = "年轻女性"
    publish: bool = True


class OutfitPostOutput(BaseModel):
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
# 推荐物品识别与参考图片收集
# ============================================================================

class VisualItemDetail(BaseModel):
    """单个需要视觉指定的推荐物品"""
    name: str
    description: str
    visual_questions: list[str]


class RecommendationAnalysis(BaseModel):
    """LLM 从研究数据中识别的推荐物品列表"""
    recommendations: list[VisualItemDetail] = []
    summary: str = ""


class ItemReferenceImages(BaseModel):
    """单个物品的参考图片（支持多张，如不同角度）"""
    item_name: str
    image_paths: list[str] = []


class ReferenceImageResult(BaseModel):
    """参考图片收集总结果（按物品组织，不绑定分组）"""
    items: list[ItemReferenceImages] = []
    skipped: bool = False

    def get_image_map(self) -> dict[str, list[Path]]:
        """获取物品名 → 图片路径列表的映射"""
        return {
            item.item_name: [Path(p) for p in item.image_paths]
            for item in self.items
            if item.image_paths
        }

    def get_item_names_with_images(self) -> list[str]:
        """获取有参考图片的物品名列表"""
        return [item.item_name for item in self.items if item.image_paths]


# ============================================================================
# 图片生成上下文
# ============================================================================

@dataclass
class ImageGenContext:
    """图片生成上下文（用于依赖注入）"""

    topic: str = ""
    image_type: str = ""
    validation_feedback: str = ""
    reference_image_map: dict[str, list[str]] = field(default_factory=dict)  # item_name → [path_str]


class GroupSpec(TypedDict, total=False):
    title: str
    indices: list[int]
    ref_items: list[str]  # 属于本组的参考图物品名（由分组 Agent 分配）


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
    ref_items: list[str]


# ============================================================================
# 研究数据
# ============================================================================

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


# ============================================================================
# 内容创作
# ============================================================================

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


# ============================================================================
# 图片生成
# ============================================================================

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
    ref_items: List[str] = []  # 属于本组的参考图物品名


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


# ============================================================================
# 图片读取
# ============================================================================

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


# ============================================================================
# 发布
# ============================================================================

class PublishResult(BaseModel):
    published: bool
    platform: str = "xiaohongshu"
    publish_time: str
    post_url: str = ""
    error_message: str = ""
    retry_count: int = 0
    content_snapshot: Optional[Dict[str, Any]] = None
    image_paths: Optional[List[str]] = None
