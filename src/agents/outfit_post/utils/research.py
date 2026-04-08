"""研究结果持久化工具"""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..schemas import ContentSource, ResearchResult
from ....utils.logger import get_logger

logger = get_logger(__name__)


def _canonicalize_url(url: str) -> str:
    """Normalize URLs before dedupe to avoid counting tracking variants twice."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme or "https"
        netloc = parts.netloc
        path = parts.path or ""
        if not netloc and parts.path.startswith("//"):
            reparsed = urlsplit("https:" + url)
            scheme, netloc, path, parts = reparsed.scheme, reparsed.netloc, reparsed.path, reparsed

        drop_keys = {
            "xsec_token",
            "xsec_source",
            "source",
            "spm",
            "spm_id_from",
            "ref",
            "ref_src",
            "igshid",
            "fbclid",
            "gclid",
        }
        kept = []
        for key, value in parse_qsl(parts.query, keep_blank_values=False):
            if key in drop_keys or key.startswith("utm_"):
                continue
            kept.append((key, value))
        query = urlencode(kept, doseq=True)
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return url.split("#", 1)[0]


def save_iteration_result(
    result: ResearchResult,
    topic: str,
    iteration: int,
    tracked_stats: dict,
    output_dir: Path | None,
    saved_files: list[str]
) -> str:
    """保存本轮研究结果到 JSON 文件"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    out_dir = output_dir if output_dir else Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / f"research_iter{iteration}_{timestamp}.json"
    dedupe_index = 1
    while filepath.exists():
        filepath = out_dir / f"research_iter{iteration}_{timestamp}_{dedupe_index}.json"
        dedupe_index += 1

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
        key = (item.title, item.content, item.item_type, item.source_ref)
        if key not in seen:
            seen.add(key)
            merged_items.append(item)

    # 去重 sources
    seen_urls = set()
    merged_sources = []
    for source in all_sources:
        raw_url = source.url if hasattr(source, "url") else source.get("url", json.dumps(source, sort_keys=True))
        canonical_url = _canonicalize_url(raw_url) or raw_url
        if canonical_url not in seen_urls:
            seen_urls.add(canonical_url)
            if isinstance(source, ContentSource):
                merged_sources.append(source.model_copy(update={"url": canonical_url}))
            else:
                source["url"] = canonical_url
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
