"""
Pydantic 数据模型
定义研究结果和内容的数据结构
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class ResearchResult(BaseModel):
    """小红书研究结果"""

    summary: str = Field(description="研究总结")
    entities: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="提取的实体（公司、价格等）"
    )
    cases: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="具体案例"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="关键词"
    )
    credibility: str = Field(
        default="medium",
        description="可信度评估 (low/medium/high)"
    )
    data_points: int = Field(
        default=0,
        description="收集的数据点数量"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "summary": "关于西安公司避坑的研究，收集了10家公司的真实案例",
                "entities": [
                    {"type": "company", "name": "某科技公司", "issue": "加班严重"}
                ],
                "cases": [
                    {"company": "某科技", "experience": "试用期不交社保"}
                ],
                "keywords": ["避坑", "西安", "公司"],
                "credibility": "high",
                "data_points": 15
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
                        "description": "声称'10家公司'，实际只列出5家",
                        "suggestion": "修改为'5家公司'或补充更多"
                    }
                ],
                "summary": "内容存在数量不一致问题，需要修改",
                "entity_usage": {
                    "research_entities": 11,
                    "used_entities": 5,
                    "usage_rate": 0.45
                }
            }
        }


class ImageReviewIssue(BaseModel):
    """图片审核问题"""

    type: str = Field(
        description="问题类型: file_missing | file_too_small | text_not_chinese | style_mismatch"
    )
    severity: str = Field(
        description="严重程度: critical | warning | info"
    )
    image_type: str = Field(
        description="图片类型: cover | detail_1 | detail_2 | all"
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
                "type": "text_not_chinese",
                "severity": "critical",
                "image_type": "cover",
                "description": "封面图文字为英文，不是中文",
                "suggestion": "重新生成，确保提示词要求中文文字"
            }
        }


class ImageReviewResult(BaseModel):
    """图片审核结果"""

    passed: bool = Field(
        description="是否通过审核"
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="质量评分（0-100）"
    )
    issues: List[ImageReviewIssue] = Field(
        default_factory=list,
        description="发现的问题列表"
    )
    summary: str = Field(
        description="审核总结"
    )
    file_check: Dict[str, bool] = Field(
        default_factory=dict,
        description="文件检查结果 {image_type: exists}"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "passed": False,
                "score": 50.0,
                "issues": [
                    {
                        "type": "file_missing",
                        "severity": "critical",
                        "image_type": "cover",
                        "description": "封面图文件不存在",
                        "suggestion": "重新生成并下载图片"
                    }
                ],
                "summary": "审核未通过，封面图缺失",
                "file_check": {
                    "cover": False,
                    "detail_1": True,
                    "detail_2": True
                }
            }
        }
