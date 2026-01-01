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
