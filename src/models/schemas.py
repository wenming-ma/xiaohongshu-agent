"""
Pydantic 数据模型
定义研究结果和内容的数据结构
"""
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Dict, Any, TypedDict


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
    validation_feedback: str = ""  # 验证失败时的反馈，用于指导下次生成


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


# ==================== Pydantic 模型 ====================


class ContentSource(BaseModel):
    """内容来源（通用）"""
    url: str = Field(description="来源链接")
    title: str = Field(description="标题")
    content_type: str = Field(
        default="post",
        description="内容类型：article/post/comment/reply"
    )
    author: Optional[str] = Field(default=None, description="作者")
    publish_time: Optional[datetime] = Field(default=None, description="发布时间")

    # 互动数据（可选）
    likes: Optional[int] = Field(default=None, description="点赞数")
    comments: Optional[int] = Field(default=None, description="评论数")
    shares: Optional[int] = Field(default=None, description="分享数")
    views: Optional[int] = Field(default=None, description="浏览数")


class ResearchResult(BaseModel):
    """研究结果（通用）"""

    # 核心数据
    summary: str = Field(description="研究总结")
    key_infos: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="提取的关键信息（名称、品牌、地点、数字等具体信息）"
    )
    cases: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="具体案例"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="关键词（用于搜索和索引）"
    )

    # 质量评估
    credibility: str = Field(
        default="medium",
        description="可信度评估 (low/medium/high)"
    )
    interaction_data_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="互动数据占比（评论、回复等，0-1）"
    )

    # 来源追踪
    sources: List[ContentSource] = Field(
        default_factory=list,
        description="内容来源列表"
    )

    # 计算字段
    @computed_field
    @property
    def data_points(self) -> int:
        """数据点总数（自动计算）"""
        return len(self.key_infos) + len(self.cases)

    @computed_field
    @property
    def sources_count(self) -> int:
        """来源数量（自动计算）"""
        return len(self.sources)

    class Config:
        json_schema_extra = {
            "example": {
                "summary": "关于某主题的研究，收集了多个关键信息和真实案例",
                "key_infos": [
                    {"type": "brand", "name": "具体品牌名", "detail": "相关描述", "source": "post_1"}
                ],
                "cases": [
                    {"title": "用户真实经历", "description": "具体问题描述", "source": "comment_1"}
                ],
                "keywords": ["关键词1", "关键词2", "关键词3"],
                "credibility": "high",
                "interaction_data_ratio": 0.45,
                "sources": [
                    {"url": "https://...", "title": "帖子标题", "content_type": "post", "likes": 1200, "comments": 300}
                ]
            }
        }


class XHSContent(BaseModel):
    """小红书内容"""

    title: str = Field(
        description="标题（15-20字）",
        min_length=10,
        max_length=30
    )
    body: str = Field(
        description="正文（包含案例）",
        min_length=100
    )
    hashtags: List[str] = Field(
        default_factory=list,
        description="标签",
        max_length=5
    )
    call_to_action: str = Field(
        default="",
        description="行动号召"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "🚨西安求职避坑指南！这些公司要注意",
                "body": "最近整理了西安10家公司的真实踩坑经历...",
                "hashtags": ["西安求职", "避坑指南", "求职攻略"],
                "call_to_action": "你还遇到过哪些坑？评论区分享💬"
            }
        }


class ReviewIssue(BaseModel):
    """审核发现的问题"""

    type: str = Field(
        description="问题类型: count_mismatch | data_missing | logic_error | format_error"
    )
    severity: str = Field(
        description="严重程度: critical | warning | info"
    )
    description: str = Field(
        description="问题描述"
    )
    suggestion: str = Field(
        description="修改建议"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "type": "count_mismatch",
                "severity": "critical",
                "description": "声称'10家公司'，实际只列出5家",
                "suggestion": "修改为'5家公司'或补充更多公司"
            }
        }


class GeneratedImage(BaseModel):
    """单张生成图片"""

    image_path: str = Field(description="图片本地路径")
    prompt_used: str = Field(description="使用的 Gemini 生成提示词")
    image_type: str = Field(description="图片类型: cover/detail_1/detail_2...")


class ImageResult(BaseModel):
    """图片生成结果（多张）"""

    images: List[GeneratedImage] = Field(
        default_factory=list,
        description="生成的图片列表"
    )
    total_count: int = Field(description="生成图片总数")
    generated_at: str = Field(description="生成时间")

    class Config:
        json_schema_extra = {
            "example": {
                "images": [
                    {
                        "image_path": "posts/20250102-西安公司/cover.png",
                        "prompt_used": "A modern minimalist poster...",
                        "image_type": "cover"
                    },
                    {
                        "image_path": "posts/20250102-西安公司/detail_1.png",
                        "prompt_used": "An infographic showing...",
                        "image_type": "detail_1"
                    }
                ],
                "total_count": 2,
                "generated_at": "2025-01-02T10:30:00"
            }
        }


class ReviewResult(BaseModel):
    """审核结果"""

    passed: bool = Field(
        description="是否通过审核"
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="质量评分（0-100）"
    )
    issues: List[ReviewIssue] = Field(
        default_factory=list,
        description="发现的问题列表"
    )
    summary: str = Field(
        description="审核总结"
    )
    entity_usage: Optional[Dict[str, Any]] = Field(
        default=None,
        description="实体使用情况统计"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "passed": False,
                "score": 65.0,
                "issues": [
                    {
                        "type": "count_mismatch",
                        "severity": "critical",
                        "description": "声称'10个要点'，实际只列出5个",
                        "suggestion": "修改为'5个要点'或补充更多"
                    }
                ],
                "summary": "内容存在数量不一致问题，需要修改",
                "entity_usage": {
                    "research_key_infos": 11,
                    "used_key_infos": 5,
                    "usage_rate": 0.45
                }
            }
        }


# ==================== 图片语义分组（ImageAgent） ====================


class ImageGroupingGroup(BaseModel):
    """图片详情图分组（语义组）"""

    title: str = Field(description="分组标题（用于该组详情图的板块标题）")
    indices: List[int] = Field(
        default_factory=list,
        description="该组包含的 key_infos 下标（0-based），必须覆盖且不重复",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="可选：分组理由（用于调试/可观测性）",
    )


class ImageGroupingPlan(BaseModel):
    """LLM 输出：key_infos 的语义分组计划"""

    groups: List[ImageGroupingGroup] = Field(
        default_factory=list,
        description="语义分组列表",
    )


class ImageGroupingReviewResult(BaseModel):
    """分组审核结果：验证分组质量与完整性"""

    passed: bool = Field(description="是否通过审核")
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="评分（0-100）",
    )
    issues: List[str] = Field(
        default_factory=list,
        description="问题列表（简洁描述）",
    )
    summary: str = Field(
        default="",
        description="审核总结",
    )


class GeminiOperationResult(BaseModel):
    """Gemini 操作结果（用于 gemini_operator Agent）"""

    success: bool = Field(description="操作是否成功完成")
    status: str = Field(description="状态描述（成功/失败原因）")
    downloaded_file: Optional[str] = Field(
        default=None,
        description="下载的文件名（如果有）"
    )


# ==================== 专用验证器模型 ====================


class GeminiConfigReview(BaseModel):
    """Gemini 配置验证结果 - 检查 Create images + Pro 模式"""

    passed: bool = Field(
        description="验证是否通过"
    )
    create_images_enabled: bool = Field(
        description="Tools -> Create images 是否已选中"
    )
    pro_mode_enabled: bool = Field(
        description="Pro 模式是否已选中"
    )
    issues: List[str] = Field(
        default_factory=list,
        description="发现的配置问题"
    )
    summary: str = Field(
        description="验证总结"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "passed": False,
                "create_images_enabled": True,
                "pro_mode_enabled": False,
                "issues": ["Pro 模式未选中，当前为 Fast 模式"],
                "summary": "Gemini 配置不正确：需要选择 Pro 模式"
            }
        }


class ImageQualityReview(BaseModel):
    """图片质量验证结果 - 检查字迹清晰度和风格"""

    passed: bool = Field(
        description="验证是否通过"
    )
    text_clarity_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="文字清晰度评分（0-100）"
    )
    style_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="风格匹配度评分（0-100）"
    )
    aspect_ratio_correct: bool = Field(
        default=True,
        description="图片比例是否为 3:4 竖版"
    )
    text_is_chinese: bool = Field(
        default=True,
        description="图片文字是否为中文"
    )
    issues: List[str] = Field(
        default_factory=list,
        description="发现的质量问题"
    )
    summary: str = Field(
        description="验证总结"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "passed": True,
                "text_clarity_score": 85.0,
                "style_score": 90.0,
                "aspect_ratio_correct": True,
                "text_is_chinese": True,
                "issues": [],
                "summary": "图片质量良好，文字清晰，风格符合小红书审美"
            }
        }


class ImageReadResult(BaseModel):
    """图片读取结果 - OCR/视觉理解（给 Tool 使用）"""

    extracted_text: str = Field(
        default="",
        description="从图片中提取的文字内容（尽量保留换行/列表/层级；看不清可留空并在 issues 说明）",
    )
    description: str = Field(
        default="",
        description="对图片整体内容的简短描述（不超过 3 句；无文字时尤为重要）",
    )
    language: str = Field(
        default="unknown",
        description="图片主要文字语言（如 zh/en/mixed/unknown）",
    )
    has_text: bool = Field(
        default=False,
        description="图片中是否存在可识别文字",
    )
    answer: str = Field(
        default="",
        description="若提供 question，可基于图片内容给出简短回答；否则为空",
    )
    issues: List[str] = Field(
        default_factory=list,
        description="识别问题（如模糊/遮挡/分辨率过低/字体过小/部分区域无法识别等）",
    )

class PublishResult(BaseModel):
    """小红书发布结果"""

    published: bool = Field(
        description="是否发布成功"
    )
    platform: str = Field(
        default="xiaohongshu",
        description="发布平台"
    )
    publish_time: str = Field(
        description="发布时间（ISO格式）"
    )
    post_url: str = Field(
        default="",
        description="发布链接（如果获取到）"
    )
    error_message: str = Field(
        default="",
        description="错误信息（失败时）"
    )
    retry_count: int = Field(
        default=0,
        description="重试次数"
    )

    # 元数据（用于失败后手动重试）
    content_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="内容快照"
    )
    image_paths: Optional[List[str]] = Field(
        default=None,
        description="图片路径列表"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "published": True,
                "platform": "xiaohongshu",
                "publish_time": "2025-01-04T10:30:00",
                "post_url": "https://www.xiaohongshu.com/explore/...",
                "error_message": "",
                "retry_count": 0,
                "content_snapshot": None,
                "image_paths": None
            }
        }
