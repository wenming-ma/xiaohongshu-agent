"""
Phase 1: 项目初始化节点
"""
from datetime import datetime
from pathlib import Path

from ..state import XHSState
from ..tools import create_project_structure, write_json


async def init_project_node(state: XHSState) -> dict:
    """
    初始化项目：
    1. 创建项目目录结构
    2. 保存project.json元数据
    3. 更新状态

    Args:
        state: 当前工作流状态

    Returns:
        更新后的状态字段
    """
    # 创建项目目录
    paths = create_project_structure(state["project_dir"])

    # 创建project.json
    project_metadata = {
        "project_id": state["project_id"],
        "topic": state["topic"],
        "target_audience": state["target_audience"],
        "num_images": state["num_images"],
        "created_at": state["created_at"],
        "status": "initialized",
        "agents_used": []
    }

    write_json(paths["project_json"], project_metadata)

    # 记录日志
    log_message = f"[{datetime.now().isoformat()}] Project initialized: {state['project_id']}"

    return {
        "initialized": True,
        "current_phase": "research",
        "logs": [log_message]
    }
