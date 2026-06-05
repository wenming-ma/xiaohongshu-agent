"""研究结果持久化与清洗工具"""
import json
from datetime import datetime
from pathlib import Path

from ..schemas import ResearchResult, ResearchItem
from ....utils.logger import get_logger

logger = get_logger(__name__)


OPERATIONAL_RESEARCH_MARKERS = (
    "研究限制说明",
    "研究限制",
    "研究过程",
    "素材状态",
    "任务完成情况说明",
    "登录弹窗限制",
    "登录弹窗",
    "登录工具返回",
    "共享 session",
    "session已登录",
    "页面仍显示登录要求",
    "平台登录限制",
    "无法绕过",
    "无法正常显示",
    "刷新页面后登录状态",
    "建议：直接在飞书",
    "浏览器 session",
    "扫码登录",
    "视频语音提取结果",
    "图片读取结果",
    "工具未发现可下载视频直链",
    "无法获取口播转写",
    "未检测到图片",
    "无图片清单可提取",
    "该帖类型返回为 video",
)

OPERATIONAL_RESEARCH_ITEM_TYPES = {
    "video_status",
    "image_status",
    "media_status",
    "tool_status",
    "login_status",
    "auth_status",
    "session_status",
    "research_status",
    "operational_status",
    "diagnostic",
    "diagnostics",
}


def is_operational_research_item(item: ResearchItem | dict) -> bool:
    """识别研究过程诊断信息，避免把它当成可发布/可成图素材。"""
    if hasattr(item, "title"):
        title = item.title or ""
        content = item.content or ""
        item_type = item.item_type or ""
    else:
        title = str(item.get("title") or item.get("name") or "")
        content = str(item.get("content") or item.get("description") or item.get("detail") or "")
        item_type = str(item.get("item_type") or item.get("type") or "")

    if item_type.strip().lower() in OPERATIONAL_RESEARCH_ITEM_TYPES:
        return True

    text = f"{item_type}\n{title}\n{content}"
    return any(marker in text for marker in OPERATIONAL_RESEARCH_MARKERS)


def _sanitize_summary(summary: str) -> str:
    if not summary:
        return summary
    blocks = summary.split("\n\n---\n\n")
    kept = [
        block
        for block in blocks
        if not any(marker in block for marker in OPERATIONAL_RESEARCH_MARKERS)
    ]
    return "\n\n---\n\n".join(kept).strip()


def sanitize_research_for_content(result: ResearchResult) -> ResearchResult:
    """移除不可发布的运行诊断信息，防止其进入内容与图片生成链路。"""
    filtered_items = [
        item
        for item in result.items
        if not is_operational_research_item(item)
    ]
    filtered_summary = _sanitize_summary(result.summary)

    removed_count = len(result.items) - len(filtered_items)
    if removed_count <= 0 and filtered_summary == result.summary:
        return result

    if removed_count:
        logger.warning("已过滤 %d 条研究过程诊断信息，避免进入内容/图片生成", removed_count)

    if not filtered_items:
        filtered_summary = "研究结果只包含运行诊断信息，已过滤；需要重新研究或补充有效内容。"

    return result.model_copy(
        update={
            "summary": filtered_summary,
            "items": filtered_items,
        }
    )


def save_iteration_result(
    result: ResearchResult,
    topic: str,
    iteration: int,
    tracked_stats: dict,
    output_dir: Path | None,
    saved_files: list[str]
) -> str:
    """保存本轮研究结果到 JSON 文件"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"research_{timestamp}.json"

    out_dir = output_dir if output_dir else Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / filename

    data = {
        "topic": topic,
        "iteration": iteration,
        "timestamp": timestamp,
        "tracked_stats": tracked_stats,
        "result": result.model_dump() if hasattr(result, "model_dump") else str(result)
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    saved_files.append(str(filepath))
    return str(filepath)


def merge_results(all_results: list[ResearchResult], tracked_stats: dict) -> ResearchResult:
    """合并多轮研究结果"""
    all_items = [item for res in all_results for item in res.items]
    all_keywords = {kw for res in all_results for kw in res.keywords}
    all_sources = [source for res in all_results for source in res.sources]

    # 去重 items
    seen = set()
    merged_items = []
    for item in all_items:
        key = f"{item.title}|{item.content}"
        if key not in seen:
            seen.add(key)
            merged_items.append(item)

    # 去重 sources
    seen_urls = set()
    merged_sources = []
    for source in all_sources:
        url = source.url if hasattr(source, 'url') else source.get("url", json.dumps(source, sort_keys=True))
        if url not in seen_urls:
            seen_urls.add(url)
            merged_sources.append(source)

    merged_summary = "\n\n---\n\n".join(
        f"【第{i+1}轮研究】\n{res.summary}"
        for i, res in enumerate(all_results)
        if res.summary
    )

    merged_result = ResearchResult(
        summary=merged_summary,
        items=merged_items,
        keywords=list(all_keywords),
        sources=merged_sources,
    )

    logger.info("合并历史数据：")
    logger.info(f"  - 内容项: {len(merged_items)} 条（来自 {len(all_results)} 轮）")
    logger.info(f"  - 关键词: {len(all_keywords)} 个")
    logger.info(f"  - 内容来源: {len(merged_sources)} 个")

    return merged_result
