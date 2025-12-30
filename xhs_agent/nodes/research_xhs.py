"""
Phase 2A: 小红书平台研究节点
使用 Playwright Deep Search 进行真实的浏览器搜索
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path

from ..state import XHSState
from ..tools.deep_search_playwright import XiaohongshuDeepSearch


async def research_xhs_node(state: XHSState) -> dict:
    """
    小红书平台研究节点 - 使用 Playwright Deep Search

    执行流程：
    1. 使用真实浏览器控制搜索小红书
    2. 深度阅读帖子详情和评论区
    3. 提取具体实体（公司名、价格、时间等）
    4. 评估可信度
    5. 保存结构化数据

    Args:
        state: 当前工作流状态

    Returns:
        更新后的状态字段（xhs_research, xhs_research_completed, logs）
    """
    topic = state["topic"]
    target_audience = state.get("target_audience", "")

    print("\n" + "=" * 60)
    print(f"🔍 Phase 2A: 小红书平台研究")
    print("=" * 60)
    print(f"主题: {topic}")
    print(f"受众: {target_audience}")
    print(f"方法: Playwright Deep Search（真实浏览器）")
    print("=" * 60)

    # 创建深度搜索引擎（使用独立的 session 目录）
    searcher = XiaohongshuDeepSearch(user_data_dir="./browser-sessions/xiaohongshu")

    # 执行深度搜索
    results = await searcher.search(
        keyword=topic,
        max_results=10,  # 深度阅读10篇帖子
        read_comments=True  # 读取评论区
    )

    # 转换为研究数据格式
    research_data = _convert_to_research_format(results, topic)

    # 保存到文件
    project_dir = Path(state["project_dir"])
    xhs_research_path = project_dir / "xiaohongshu-research.json"

    with open(xhs_research_path, "w", encoding="utf-8") as f:
        json.dump(research_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 小红书研究完成")
    print(f"   - 深度阅读: {len(results)} 篇帖子")
    print(f"   - 数据点: {research_data['data_points']} 个")
    print(f"   - 实体: {len(research_data['entities'])} 个")
    print(f"   - 保存路径: {xhs_research_path}")

    # 记录日志
    log_message = f"[{datetime.now().isoformat()}] XHS Deep Search completed: {len(results)} posts, {research_data['data_points']} data points"

    return {
        "xhs_research": research_data,
        "xhs_research_completed": True,
        "logs": [log_message]
    }


def _convert_to_research_format(results: list, topic: str) -> dict:
    """
    将 Deep Search 结果转换为研究数据格式

    Args:
        results: DeepSearchResult 列表
        topic: 搜索主题

    Returns:
        研究数据字典
    """
    # 收集所有实体
    all_entities = []
    for result in results:
        for entity in result.extracted_entities:
            all_entities.append({
                "name": entity.get("value", ""),
                "type": entity.get("type", "unknown"),
                "source": result.title,
                "url": result.url,
                "credibility": result.credibility
            })

    # 构建案例
    cases = []
    for result in results:
        if result.content:
            cases.append({
                "title": result.title,
                "author": result.author,
                "content": result.content[:300],  # 截取前300字
                "likes": result.likes,
                "comments": result.comments_count,
                "url": result.url,
                "credibility": result.credibility
            })

    # 提取关键词（从标题中提取）
    keywords = set()
    for result in results:
        # 简单的关键词提取：分词并过滤
        words = result.title.split()
        for word in words:
            if len(word) >= 2:
                keywords.add(word)

    # 计算总体可信度
    if results:
        high_count = sum(1 for r in results if r.credibility == "high")
        medium_count = sum(1 for r in results if r.credibility == "medium")

        if high_count > len(results) / 2:
            overall_credibility = "high"
        elif high_count + medium_count > len(results) / 2:
            overall_credibility = "medium"
        else:
            overall_credibility = "low"
    else:
        overall_credibility = "low"

    # 生成研究总结
    summary = f"从小红书平台深度搜索'{topic}'，共阅读{len(results)}篇帖子，提取{len(all_entities)}个具体实体。"

    return {
        "summary": summary,
        "entities": all_entities,
        "cases": cases[:10],  # 最多10个案例
        "keywords": list(keywords)[:20],  # 最多20个关键词
        "credibility": overall_credibility,
        "data_points": len(results),
        "total_likes": sum(r.likes for r in results),
        "total_comments": sum(r.comments_count for r in results),
        "platform": "xiaohongshu",
        "search_method": "playwright_deep_search",
        "timestamp": datetime.now().isoformat()
    }
