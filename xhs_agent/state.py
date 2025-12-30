"""
LangGraph 状态定义
用于 Xiaohongshu 内容创建工作流
"""
from typing import TypedDict, Annotated, Sequence
from datetime import datetime
import operator


class XHSState(TypedDict):
    """Xiaohongshu 内容创建工作流的完整状态"""

    # === 输入参数 ===
    topic: str                      # 主题
    target_audience: str            # 目标受众
    num_images: int                 # 需要的图片数量（默认3）

    # === 项目元数据 ===
    project_id: str                 # 项目ID（时间戳-topic-slug）
    project_dir: str                # 项目目录路径
    created_at: str                 # 创建时间（ISO格式）

    # === Phase 1: 初始化 ===
    initialized: bool               # 是否已初始化

    # === Phase 2A: 研究阶段 ===
    xhs_research: dict | None       # 小红书平台研究数据
    web_research: dict | None       # 多平台网络研究数据
    research_completed: bool        # 两个研究是否都完成

    # === Phase 2B: 内容合成 ===
    research_summary: dict | None   # 研究数据综合总结
    content: dict | None            # 最终发布内容
    #   content schema:
    #   {
    #       "title": str,                # 标题
    #       "body": str,                 # 正文
    #       "hashtags": list[str],       # 标签
    #       "image_descriptions": list[str],  # 图片描述
    #       "call_to_action": str,       # CTA
    #       "data_sources_note": str     # 数据来源说明
    #   }

    # === Phase 3: 图片生成 ===
    images: Annotated[list[str], operator.add]  # 生成的图片路径列表
    images_generated: bool          # 图片是否生成完成

    # === Phase 4: 发布 ===
    publish_result: dict | None     # 发布结果
    #   publish_result schema:
    #   {
    #       "status": "success" | "failed",
    #       "post_url": str,
    #       "post_id": str,
    #       "published_at": str,
    #       "images_uploaded": int,
    #       "error": str | None
    #   }

    # === 全局状态 ===
    current_phase: str              # 当前阶段（init/research/synthesize/generate/publish/completed）
    errors: Annotated[list[str], operator.add]  # 错误列表
    logs: Annotated[list[str], operator.add]    # 日志列表


def create_initial_state(topic: str, target_audience: str = "年轻女性", num_images: int = 3) -> XHSState:
    """创建初始状态"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    topic_slug = topic.lower().replace(" ", "-")[:30]
    project_id = f"{timestamp}-{topic_slug}"

    return XHSState(
        # 输入
        topic=topic,
        target_audience=target_audience,
        num_images=num_images,

        # 项目元数据
        project_id=project_id,
        project_dir=f"posts/{project_id}",
        created_at=datetime.now().isoformat(),

        # 阶段状态
        initialized=False,
        research_completed=False,
        images_generated=False,

        # 数据
        xhs_research=None,
        web_research=None,
        research_summary=None,
        content=None,
        images=[],
        publish_result=None,

        # 全局
        current_phase="init",
        errors=[],
        logs=[]
    )
