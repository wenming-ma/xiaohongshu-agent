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

    # 互动数据（可选）
    likes: Optional[int] = Field(default=None, description="点赞数")
    comments: Optional[int] = Field(default=None, description="评论数")


class ResearchResult(BaseModel):
    """简化的研究结果"""

    # 核心数据
    summary: str = Field(description="研究总结")
    items: List[ResearchItem] = Field(
        default_factory=list,
        description="研究内容项列表（统一的关键信息和案例）"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="关键词（用于搜索和索引）"
    )

    # 来源追踪
    sources: List[ContentSource] = Field(
        default_factory=list,
        description="内容来源列表"
    )

    # 计算字段
    @computed_field
    @property
    def items_count(self) -> int:
        """内容项总数（自动计算）"""
        return len(self.items)

    @computed_field
    @property
    def sources_count(self) -> int:
        """来源数量（自动计算）"""
        return len(self.sources)

    class Config:
        json_schema_extra = {
            "example": {
                "summary": "关于某主题的研究，收集了多个关键信息和真实案例",
                "items": [
                    {
                        "title": "具体品牌名",
                        "content": "品牌相关描述和详细信息",
                        "item_type": "brand",
                        "source_ref": "post_1"
                    },
                    {
                        "title": "用户真实经历",
                        "content": "具体问题描述和解决方案",
                        "item_type": "case",
                        "source_ref": "comment_1"
                    }
                ],
                "keywords": ["关键词1", "关键词2", "关键词3"],
                "sources": [
                    {
                        "url": "https://www.xiaohongshu.com/explore/...",
                        "title": "帖子标题",
                        "domain": "xiaohongshu.com",
                        "likes": 1200,
                        "comments": 300
                    }
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


# ==================== 专用验证器模型 ====================


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
