"""
LangGraph Xiaohongshu Agent System
"""
from .state import XHSState, create_initial_state
from .graph import create_xiaohongshu_workflow, WORKFLOW_VISUALIZATION
from .nodes import (
    init_project_node,
    research_xhs_node,
    research_web_node,
    synthesize_node,
    generate_images_node,
    publish_node
)
from .tools import (
    FileOperations,
    write_json,
    read_json,
    write_text,
    read_text,
    ensure_dir,
    create_project_structure
)

__version__ = "0.1.0"
__all__ = [
    "XHSState",
    "create_initial_state",
    "create_xiaohongshu_workflow",
    "WORKFLOW_VISUALIZATION",
    # Nodes
    "init_project_node",
    "research_xhs_node",
    "research_web_node",
    "synthesize_node",
    "generate_images_node",
    "publish_node",
    # Tools
    "FileOperations",
    "write_json",
    "read_json",
    "write_text",
    "read_text",
    "ensure_dir",
    "create_project_structure"
]
