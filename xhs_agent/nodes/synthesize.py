"""
Phase 2B: 内容合成节点
使用 Claude Sonnet-4.5 进行高质量创作
"""
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser

from ..state import XHSState
from ..tools import write_json
from config import get_model_for_node


SYSTEM_PROMPT = """你是一位专业的小红书内容创作专家，擅长将小红书平台数据转化为吸引人的高质量内容。

你的任务是：
1. 深入分析xiaohongshu-research.json中的所有数据
2. 提取具体的公司名、案例、细节
3. 创作数据驱动、具体且吸引人的小红书帖子

内容创作要求：
- **标题**：15-20字，包含emoji，吸引眼球
- **正文**：
  * 包含3-5+个具体公司/实体名称
  * 每个实体附带具体细节（金额/地址/时间）
  * 至少1个详细案例 + 时间线
  * 提供可操作的避坑建议
- **标签**：3-5个相关标签
- **图片描述**：3张图片，每个描述50-100+字
  * 精确颜色（如 #FFE5F0）
  * 完整布局和构图
  * 所有文本内容
  * 设计风格和氛围

返回JSON格式：
{
  "title": "15-20字emoji标题",
  "body": "正文内容...",
  "hashtags": ["标签1", "标签2", "标签3"],
  "image_descriptions": [
    "图1：50-100+字超详细描述",
    "图2：50-100+字超详细描述",
    "图3：50-100+字超详细描述"
  ],
  "call_to_action": "互动引导文案",
  "entities_used": ["公司1", "公司2", "公司3"]
}
"""


async def synthesize_node(state: XHSState) -> dict:
    """
    内容合成节点 - 基于小红书研究数据创作高质量内容

    Args:
        state: 当前工作流状态

    Returns:
        更新后的状态字段（research_summary, content）
    """
    topic = state["topic"]
    target_audience = state["target_audience"]
    xhs_research = state.get("xhs_research", {})

    # 获取模型（Claude - 创作质量高）
    llm = get_model_for_node("synthesize")
    parser = JsonOutputParser()

    # 构建提示词
    user_prompt = f"""
主题：{topic}
目标受众：{target_audience}

# 小红书研究数据
{str(xhs_research)[:3000]}

请基于以上小红书研究数据：
1. 提取所有具体的公司名、案例、细节
2. 创作一篇数据丰富、吸引人的小红书帖子
3. 生成3张图片的超详细描述（每个50-100+字）

请严格按照JSON schema返回结果。
"""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt)
    ]

    # 调用LLM
    response = await llm.ainvoke(messages)

    # 解析JSON
    try:
        content_data = parser.parse(response.content)
    except Exception as e:
        # 如果解析失败，创建基础结构
        content_data = {
            "title": "创作失败",
            "body": response.content[:500],
            "hashtags": ["避坑", "经验分享"],
            "image_descriptions": ["图片描述1", "图片描述2", "图片描述3"],
            "call_to_action": "欢迎评论",
            "entities_used": [],
            "parse_error": str(e)
        }

    # 创建研究总结
    research_summary = {
        "xhs_data_points": xhs_research.get("data_points", 0),
        "total_entities": len(content_data.get("entities_used", [])),
        "synthesis_timestamp": datetime.now().isoformat()
    }

    # 保存文件
    project_dir = Path(state["project_dir"])
    write_json(project_dir / "research-summary.json", research_summary)
    write_json(project_dir / "content.json", content_data)

    # 记录日志
    log_message = f"[{datetime.now().isoformat()}] Content synthesized: {len(content_data.get('entities_used', []))} entities from XHS"

    return {
        "research_summary": research_summary,
        "content": content_data,
        "current_phase": "generate",
        "logs": [log_message]
    }
