"""XHS Image Post Tool Schemas - 工具输入输出数据模型"""

from dataclasses import dataclass
from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Dict, Any, TypedDict


# ==================== 工具输入输出 ====================


class XHSImagePostInput(BaseModel):
    """小红书图文帖子工具输入"""

    topic: str = Field(description="研究主题（如：西安公司避坑指南）")
    audience: str = Field(description="目标受众（如：求职者）")
    generate_image: bool = Field(default=True, description="是否生成配图")
    publish: bool = Field(default=True, description="是否发布到小红书")


class XHSImagePostOutput(BaseModel):
    """小红书图文帖子工具输出"""

    success: bool = Field(description="工作流是否成功完成")
    title: str = Field(default="", description="生成的标题")
    body_preview: str = Field(default="", description="正文预览（前200字）")
    hashtags: list[str] = Field(default_factory=list, description="生成的话题标签")
    image_count: int = Field(default=0, description="生成的图片数量")
    image_paths: list[str] = Field(default_factory=list, description="图片路径列表")
    published: bool = Field(default=False, description="是否已发布")
    post_url: str | None = Field(default=None, description="发布后的帖子链接")
    output_dir: str = Field(default="", description="输出目录路径")
    error_message: str | None = Field(default=None, description="错误信息（失败时）")


# ==================== Dataclass 类型定义（用于依赖注入）====================


@dataclass
class ImageGenContext:
    """
    图片生成上下文（用于 Pydantic AI 依赖注入）

    在验证失败重试时，ExternalValidator 会更新 validation_feedback 字段，
    提示词生成 Agent 的动态 system_prompt 会读取该字段并加入提示词。
    """
    topic: str = ""
    image_type: str = ""
    validation_feedback: str = ""


# ==================== TypedDict 类型定义 ====================


class GroupSpec(TypedDict):
    """语义分组规格（用于 ImageAgent 内部传递）"""
    title: str
    indices: list[int]


class CompactKeyInfo(TypedDict):
    """精简的 key_info 表示（用于 LLM 输入，降低 token）"""
    index: int
    type: str | None
    name: str
    text: str


class ImageTypeSpec(TypedDict, total=False):
    """图片生成规格（cover 或 detail_N）"""
    type: str           # "cover" 或 "detail_N"
    desc: str           # 图片描述
    group_title: str    # 仅 detail：分组标题
    indices: list[int]  # 仅 detail：key_info 索引列表


# ==================== Research 相关模型 ====================


class ResearchItem(BaseModel):
    """统一的研究内容项（替代 key_infos 和 cases）"""
    title: str = Field(description="标题或名称（如：公司名、品牌名、案例标题）")
    content: str = Field(description="详细内容描述")
    item_type: Optional[str] = Field(default=None, description="内容类型（如：brand, company, case, experience, tip）")
    source_ref: Optional[str] = Field(default=None, description="来源引用（如：post_1, comment_2）")


class ContentSource(BaseModel):
    """简化的内容来源"""
    url: str = Field(description="来源链接")
    title: str = Field(description="标题")
    domain: str = Field(description="网站域名（从 URL 提取）")
    likes: Optional[int] = Field(default=None, description="点赞数")
    comments: Optional[int] = Field(default=None, description="评论数")


class ResearchResult(BaseModel):
    """简化的研究结果"""

    summary: str = Field(description="研究总结")
    items: List[ResearchItem] = Field(
        default_factory=list,
        description="研究内容项列表（统一的关键信息和案例）"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="关键词（用于搜索和索引）"
    )
    sources: List[ContentSource] = Field(
        default_factory=list,
        description="内容来源列表"
    )

    @computed_field
    @property
    def items_count(self) -> int:
        return len(self.items)

    @computed_field
    @property
    def sources_count(self) -> int:
        return len(self.sources)


# ==================== Content 相关模型 ====================


class XHSContent(BaseModel):
    """小红书内容"""

    title: str = Field(description="标题（15-20字）", min_length=10, max_length=30)
    body: str = Field(description="正文（包含案例）", min_length=100)
    hashtags: List[str] = Field(default_factory=list, description="标签", max_length=5)
    call_to_action: str = Field(default="", description="行动号召")


class ReviewIssue(BaseModel):
    """审核发现的问题"""

    type: str = Field(description="问题类型: count_mismatch | data_missing | logic_error | format_error")
    severity: str = Field(description="严重程度: critical | warning | info")
    description: str = Field(description="问题描述")
    suggestion: str = Field(description="修改建议")


class ReviewResult(BaseModel):
    """审核结果"""

    passed: bool = Field(description="是否通过审核")
    score: float = Field(default=0.0, ge=0.0, le=100.0, description="质量评分（0-100）")
    issues: List[ReviewIssue] = Field(default_factory=list, description="发现的问题列表")
    summary: str = Field(description="审核总结")
    entity_usage: Optional[Dict[str, Any]] = Field(default=None, description="实体使用情况统计")


# ==================== Image 相关模型 ====================


class GeneratedImage(BaseModel):
    """单张生成图片"""

    image_path: str = Field(description="图片本地路径")
    prompt_used: str = Field(description="使用的 Gemini 生成提示词")
    image_type: str = Field(description="图片类型: cover/detail_1/detail_2...")


class ImageResult(BaseModel):
    """图片生成结果（多张）"""

    images: List[GeneratedImage] = Field(default_factory=list, description="生成的图片列表")
    total_count: int = Field(description="生成图片总数")
    generated_at: str = Field(description="生成时间")


class ImageGroupingGroup(BaseModel):
    """图片详情图分组（语义组）"""

    title: str = Field(description="分组标题（用于该组详情图的板块标题）")
    indices: List[int] = Field(default_factory=list, description="该组包含的 key_infos 下标（0-based），必须覆盖且不重复")
    rationale: Optional[str] = Field(default=None, description="可选：分组理由（用于调试/可观测性）")


class ImageGroupingPlan(BaseModel):
    """LLM 输出：key_infos 的语义分组计划"""

    groups: List[ImageGroupingGroup] = Field(default_factory=list, description="语义分组列表")


class ImageGroupingReviewResult(BaseModel):
    """分组审核结果：验证分组质量与完整性"""

    passed: bool = Field(description="是否通过审核")
    score: float = Field(default=0.0, ge=0.0, le=100.0, description="评分（0-100）")
    issues: List[str] = Field(default_factory=list, description="问题列表（简洁描述）")
    summary: str = Field(default="", description="审核总结")


class ImageQualityReview(BaseModel):
    """图片质量验证结果 - 检查字迹清晰度和风格"""

    passed: bool = Field(description="验证是否通过")
    text_clarity_score: float = Field(default=0.0, ge=0.0, le=100.0, description="文字清晰度评分（0-100）")
    style_score: float = Field(default=0.0, ge=0.0, le=100.0, description="风格匹配度评分（0-100）")
    aspect_ratio_correct: bool = Field(default=True, description="图片比例是否为 3:4 竖版")
    text_is_chinese: bool = Field(default=True, description="图片文字是否为中文")
    issues: List[str] = Field(default_factory=list, description="发现的质量问题")
    summary: str = Field(description="验证总结")


class ImageReadResult(BaseModel):
    """图片读取结果 - OCR/视觉理解（给 Tool 使用）"""

    extracted_text: str = Field(default="", description="从图片中提取的文字内容")
    description: str = Field(default="", description="对图片整体内容的简短描述")
    language: str = Field(default="unknown", description="图片主要文字语言")
    has_text: bool = Field(default=False, description="图片中是否存在可识别文字")
    answer: str = Field(default="", description="若提供 question，可基于图片内容给出简短回答")
    issues: List[str] = Field(default_factory=list, description="识别问题")


# ==================== Publish 相关模型 ====================


class PublishResult(BaseModel):
    """小红书发布结果"""

    published: bool = Field(description="是否发布成功")
    platform: str = Field(default="xiaohongshu", description="发布平台")
    publish_time: str = Field(description="发布时间（ISO格式）")
    post_url: str = Field(default="", description="发布链接（如果获取到）")
    error_message: str = Field(default="", description="错误信息（失败时）")
    retry_count: int = Field(default=0, description="重试次数")
    content_snapshot: Optional[Dict[str, Any]] = Field(default=None, description="内容快照")
    image_paths: Optional[List[str]] = Field(default=None, description="图片路径列表")
