"""
LangGraph 图定义 - Xiaohongshu 内容创建工作流

简化版：仅专注小红书平台研究
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import XHSState
from .nodes import (
    init_project_node,
    research_xhs_node,
    synthesize_node,
    generate_images_node,
    publish_node
)


def create_xiaohongshu_workflow():
    """
    创建小红书内容创建工作流图（简化版）

    工作流阶段：
    Phase 1: 初始化 → init_project
    Phase 2: 小红书研究 → research_xhs
    Phase 3: 内容合成 → synthesize
    Phase 4: 图片生成 → generate_images
    Phase 5: 发布 → publish
    """

    # 创建状态图
    workflow = StateGraph(XHSState)

    # === 添加节点 ===
    workflow.add_node("init_project", init_project_node)
    workflow.add_node("research_xhs", research_xhs_node)
    workflow.add_node("synthesize", synthesize_node)
    workflow.add_node("generate_images", generate_images_node)
    workflow.add_node("publish", publish_node)

    # === 定义流程（串行）===
    workflow.add_edge(START, "init_project")
    workflow.add_edge("init_project", "research_xhs")
    workflow.add_edge("research_xhs", "synthesize")
    workflow.add_edge("synthesize", "generate_images")
    workflow.add_edge("generate_images", "publish")
    workflow.add_edge("publish", END)

    # 编译图（带checkpointing）
    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)

    return app


# === 图的可视化表示（文本）===
WORKFLOW_VISUALIZATION = """
小红书内容创建工作流图（简化版）：

    START
      |
      v
 [init_project]
      |
      v
 [research_xhs]  ← 仅小红书平台
      |
      v
  [synthesize]
      |
      v
[generate_images]
      |
      v
   [publish]
      |
      v
     END

特性：
✅ 专注小红书：仅收集小红书平台数据
✅ 串行流程：更稳定、更快速
✅ Checkpointing：任意节点失败可恢复
"""


if __name__ == "__main__":
    print(WORKFLOW_VISUALIZATION)
    print("\n创建工作流...")
    app = create_xiaohongshu_workflow()
    print("✅ 工作流创建成功！")
