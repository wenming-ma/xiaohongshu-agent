"""
研究结果持久化模块

包含：
- 保存单轮研究结果
- 合并多轮研究结果
"""
import json
from datetime import datetime
from pathlib import Path

from ...models.schemas import ResearchResult
from ...utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# 保存结果
# ============================================================================

def save_iteration_result(
    result: ResearchResult,
    topic: str,
    iteration: int,
    tracked_stats: dict,
    output_dir: Path | None,
    saved_files: list[str]
) -> str:
    """
    保存本轮研究结果到 JSON 文件

    Args:
        result: 研究结果
        topic: 研究主题
        iteration: 迭代次数
        tracked_stats: 追踪统计
        output_dir: 输出目录
        saved_files: 已保存文件列表（会被修改）

    Returns:
        保存的文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"research_{timestamp}.json"

    if output_dir:
        out_dir = output_dir
    else:
        out_dir = Path("output")
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


# ============================================================================
# 合并结果
# ============================================================================

def _deduplicate_items(items: list[dict]) -> list[dict]:
    """去重字典列表（基于 JSON 序列化）"""
    seen = set()
    unique = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _average_credibility(credibilities: list[str]) -> str:
    """计算 credibility 平均值"""
    credibility_map = {"low": 1, "medium": 2, "high": 3}
    credibility_reverse = {1: "low", 2: "medium", 3: "high"}

    scores = [credibility_map.get(c, 2) for c in credibilities]
    avg_score = round(sum(scores) / len(scores)) if scores else 2

    return credibility_reverse.get(avg_score, "medium")


def merge_results(
    all_results: list[ResearchResult],
    tracked_stats: dict
) -> ResearchResult:
    """
    合并多轮研究结果

    Args:
        all_results: 所有轮次的研究结果
        tracked_stats: 追踪统计

    Returns:
        合并后的研究结果
    """
    # 收集所有数据
    all_key_infos = [info for res in all_results for info in res.key_infos]
    all_cases = [case for res in all_results for case in res.cases]
    all_keywords = {kw for res in all_results for kw in res.keywords}
    all_sources = [source for res in all_results for source in res.sources]

    # 去重
    merged_key_infos = _deduplicate_items(all_key_infos)
    merged_cases = _deduplicate_items(all_cases)

    # sources 按 URL 去重
    seen_urls = set()
    merged_sources = []
    for source in all_sources:
        url = source.url if hasattr(source, 'url') else source.get("url", json.dumps(source, sort_keys=True))
        if url not in seen_urls:
            seen_urls.add(url)
            merged_sources.append(source)

    # 拼接 summary
    merged_summary = "\n\n---\n\n".join(
        f"【第{i+1}轮研究】\n{res.summary}"
        for i, res in enumerate(all_results)
        if res.summary
    )

    # 计算 credibility 平均值
    merged_credibility = _average_credibility([res.credibility for res in all_results])

    merged_result = ResearchResult(
        summary=merged_summary,
        key_infos=merged_key_infos,
        cases=merged_cases,
        keywords=list(all_keywords),
        credibility=merged_credibility,
        sources=merged_sources,
        interaction_data_ratio=all_results[-1].interaction_data_ratio
    )

    logger.info("合并历史数据：")
    logger.info(f"  - 关键信息: {len(merged_key_infos)} 条（来自 {len(all_results)} 轮）")
    logger.info(f"  - 案例: {len(merged_cases)} 个")
    logger.info(f"  - 关键词: {len(all_keywords)} 个")
    logger.info(f"  - 内容来源: {len(merged_sources)} 个")

    return merged_result
