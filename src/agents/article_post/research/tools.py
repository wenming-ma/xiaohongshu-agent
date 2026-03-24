"""Local tools for article research."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import Tool

from ....config.settings import PathConfig
from ....utils.logger import get_logger
from ....utils.subtitle_generator import WhisperTranscriber
from ..schemas import SavedSourceIndex, SourceChunk, SourceDigest, SourceExcerpt

logger = get_logger(__name__)

ARTICLE_MEDIA_DOMAINS = [
    "allure.com",
    "byrdie.com",
    "whowhatwear.com",
    "thecut.com",
    "refinery29.com",
    "glamour.com",
    "womenshealthmag.com",
    "cosmopolitan.com",
    "elle.com",
    "vogue.com",
    "harpersbazaar.com",
    "bustle.com",
]

VIDEO_MEDIA_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
]

VIDEO_HOST_PATTERNS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "tiktok.com",
    "player.vimeo.com",
)


class SearchPlan(BaseModel):
    article_queries: list[str] = Field(default_factory=list)
    video_queries: list[str] = Field(default_factory=list)
    notes: str = ""


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    domain: str = ""
    rank: int = 0


class ReadPageResult(BaseModel):
    ok: bool = False
    url: str = ""
    final_url: str = ""
    title: str = ""
    author: str = ""
    published_at: str = ""
    text: str = ""
    headings: list[str] = []
    paragraphs: list[str] = []
    video_urls: list[str] = []
    iframe_urls: list[str] = []
    engagement_hint: str = ""
    paywall_status: str = "public"
    notes: str = ""


class TranscriptResult(BaseModel):
    success: bool = False
    transcript: str = ""
    language: str = "unknown"
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class CollectedSource:
    ref: str
    url: str
    domain: str
    title: str
    author: str
    published_at: str
    snippet: str
    text: str
    headings: list[str]
    source_type: str
    engagement_hint: str
    paywall_status: str
    paragraphs: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    transcript: str = ""
    duration_seconds: float = 0.0


@dataclass
class CollectedSourceCandidate:
    url: str
    domain: str
    title: str
    author: str
    published_at: str
    snippet: str
    text: str
    headings: list[str]
    source_type: str
    engagement_hint: str
    paywall_status: str
    paragraphs: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    transcript: str = ""
    duration_seconds: float = 0.0
    search_rank: int = 0
    query: str = ""


def _load_keys(env_var: str) -> list[str]:
    """Load comma-separated API keys from an env var, filtering blanks."""
    raw = os.getenv(env_var, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


class _KeyRotator:
    """Round-robin key selector with automatic exhaustion tracking."""

    def __init__(self, keys: list[str]):
        self._keys = list(keys)
        self._index = 0
        self._exhausted: set[str] = set()

    def next(self) -> str | None:
        available = [k for k in self._keys if k not in self._exhausted]
        if not available:
            return None
        key = available[self._index % len(available)]
        self._index += 1
        return key

    def mark_exhausted(self, key: str) -> None:
        self._exhausted.add(key)
        logger.info("API key …%s marked exhausted, %d remaining",
                     key[-6:], len(self._keys) - len(self._exhausted))


class DomainSearchClient:
    def __init__(self):
        self._timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        self._serper_keys = _KeyRotator(_load_keys("SERPER_API_KEY"))
        self._tavily_keys = _KeyRotator(_load_keys("TAVILY_API_KEY"))

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []

        serper_key = self._serper_keys.next()
        if serper_key:
            try:
                return await self._search_serper(query, max_results, serper_key)
            except httpx.HTTPStatusError as exc:
                logger.warning("Serper search failed: %s", exc)
                if exc.response.status_code in (400, 401, 403, 429):
                    self._serper_keys.mark_exhausted(serper_key)
            except Exception as exc:
                logger.warning("Serper search failed: %s", exc)

        tavily_key = self._tavily_keys.next()
        if tavily_key:
            try:
                return await self._search_tavily(query, max_results, tavily_key)
            except httpx.HTTPStatusError as exc:
                logger.warning("Tavily search failed: %s", exc)
                if exc.response.status_code in (401, 403, 429, 432):
                    self._tavily_keys.mark_exhausted(tavily_key)
            except Exception as exc:
                logger.warning("Tavily search failed: %s", exc)

        return await self._search_duckduckgo(query, max_results)

    async def _search_serper(self, query: str, max_results: int, api_key: str) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": max_results},
            )
            response.raise_for_status()
            data = response.json()

        results: list[SearchResult] = []
        for idx, item in enumerate((data.get("organic") or [])[:max_results], start=1):
            url = self._canonicalize_url(item.get("link") or "")
            results.append(
                SearchResult(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    snippet=(item.get("snippet") or "").strip(),
                    domain=urlsplit(url).netloc.lower(),
                    rank=idx,
                )
            )
        return results

    async def _search_tavily(self, query: str, max_results: int, api_key: str) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                },
            )
            response.raise_for_status()
            data = response.json()

        results: list[SearchResult] = []
        for idx, item in enumerate((data.get("results") or [])[:max_results], start=1):
            url = self._canonicalize_url(item.get("url") or "")
            results.append(
                SearchResult(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    snippet=(item.get("content") or "").strip(),
                    domain=urlsplit(url).netloc.lower(),
                    rank=idx,
                )
            )
        return results

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[SearchResult]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": _user_agent()})
            response.raise_for_status()
            html = response.text

        matches = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            html,
            flags=re.S,
        )
        results: list[SearchResult] = []
        for idx, (href, title, snippet) in enumerate(matches[:max_results], start=1):
            clean_url = self._canonicalize_url(unescape(href))
            results.append(
                SearchResult(
                    title=_strip_tags(unescape(title)),
                    url=clean_url,
                    snippet=_strip_tags(unescape(snippet)),
                    domain=urlsplit(clean_url).netloc.lower(),
                    rank=idx,
                )
            )
        return results

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        if not url:
            return ""
        parts = urlsplit(url)
        kept = []
        for key, value in parse_qsl(parts.query, keep_blank_values=False):
            if key.startswith("utm_") or key in {"ref", "source", "spm", "fbclid", "gclid"}:
                continue
            kept.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept, doseq=True), ""))


class ArticlePageReader:
    """Article content extractor using trafilatura (no browser needed)."""

    def __init__(self):
        self._timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    async def read_page(self, url: str) -> ReadPageResult:
        import trafilatura

        try:
            html = await self._fetch_html(url)
            if not html:
                logger.warning("页面获取失败(空响应): %s", url)
                return ReadPageResult(url=url, notes="HTTP 请求返回空内容")

            metadata = trafilatura.extract_metadata(html)
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
                deduplicate=True,
            ) or ""

            title = (metadata.title if metadata else "") or ""
            author = (metadata.author if metadata else "") or ""
            published_at = (metadata.date if metadata else "") or ""

            # Extract headings and paragraphs from HTML
            headings, paragraphs = _extract_structure(html)

            # Simple paywall detection on raw HTML
            paywall = _detect_paywall(html)

            result = ReadPageResult(
                ok=True,
                url=url,
                final_url=url,
                title=title,
                author=author,
                published_at=published_at,
                text=text[:25000],
                headings=headings[:30],
                paragraphs=paragraphs[:120],
                paywall_status="login_required" if paywall else "public",
                notes="Possible paywall detected" if paywall else "",
            )
            logger.info(
                "页面提取成功: %s text=%d paywall=%s headings=%d",
                url, len(result.text), result.paywall_status, len(result.headings),
            )
            return result
        except Exception as exc:
            logger.warning("页面提取异常: %s %s: %s", url, type(exc).__name__, exc)
            return ReadPageResult(url=url, notes=f"{type(exc).__name__}: {exc}")

    async def _fetch_html(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _user_agent()},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text


class GenericVideoTranscriber:
    def __init__(self):
        self._transcriber = WhisperTranscriber()

    async def transcribe(self, url: str) -> TranscriptResult:
        temp_dir = Path(tempfile.mkdtemp(prefix="article-video-", dir=PathConfig.DOWNLOADS_DIR))
        try:
            video_path = await self._download(url, temp_dir)
            transcript = await self._transcriber.transcribe(video_path)
            return TranscriptResult(
                success=transcript.success,
                transcript=transcript.transcript,
                language=transcript.language,
                duration_seconds=transcript.duration_seconds,
                error_message=transcript.error_message,
            )
        except Exception as exc:
            return TranscriptResult(error_message=f"{type(exc).__name__}: {exc}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _download(self, url: str, temp_dir: Path) -> Path:
        import yt_dlp

        output_template = str(temp_dir / "source.%(ext)s")

        def _sync_download() -> Path:
            opts = {
                "format": "best[ext=mp4]/best",
                "outtmpl": output_template,
                "quiet": True,
                "no_warnings": True,
                "merge_output_format": "mp4",
                "socket_timeout": 30,
                "retries": 2,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = Path(ydl.prepare_filename(info))
                merged = filename.with_suffix(".mp4")
                if merged.exists():
                    return merged
                return filename

        loop = asyncio.get_running_loop()
        downloaded_path = await loop.run_in_executor(None, _sync_download)
        return downloaded_path


class LocalEvidenceStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.sources_dir = self.base_dir / "research_sources"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.digests_path = self.base_dir / "digests.json"
        self.index_path = self.base_dir / "source_index.json"

    def save_sources(
        self,
        sources: list[CollectedSource],
        chunks_by_source: dict[str, list[SourceChunk]],
    ) -> list[str]:
        saved_paths: list[str] = []
        index_entries = self._load_index_entries()
        seen_refs = {entry.source_ref for entry in index_entries}

        for source in sources:
            chunks = chunks_by_source.get(source.ref, [])
            path = self.sources_dir / f"{source.ref}.json"
            payload = {
                "source": asdict(source),
                "chunks": [chunk.model_dump() for chunk in chunks],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            saved_paths.append(str(path))

            entry = SavedSourceIndex(
                source_ref=source.ref,
                source_type=source.source_type,
                title=source.title,
                domain=source.domain,
                source_path=str(path),
                chunk_count=len(chunks),
            )
            if source.ref not in seen_refs:
                index_entries.append(entry)
                seen_refs.add(source.ref)
            else:
                for idx, current in enumerate(index_entries):
                    if current.source_ref == source.ref:
                        index_entries[idx] = entry
                        break

        self.index_path.write_text(
            json.dumps([entry.model_dump(mode="json") for entry in index_entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return saved_paths

    def save_digests(self, digests: list[SourceDigest]) -> str:
        payload = [digest.model_dump(mode="json") for digest in digests]
        self.digests_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(self.digests_path)

    def get_tools(self) -> list[Tool]:
        return [
            Tool(self.list_saved_sources, takes_ctx=False),
            Tool(self.read_source_digest, takes_ctx=False),
            Tool(self.read_source_excerpt, takes_ctx=False),
            Tool(self.read_primary_source, takes_ctx=False),
        ]

    async def list_saved_sources(self) -> str:
        """列出当前 research 输出目录下可读取的来源摘要索引。"""
        entries = [entry.model_dump(mode="json") for entry in self._load_index_entries()]
        return json.dumps(entries, ensure_ascii=False, indent=2)

    async def read_source_digest(self, source_ref: str) -> str:
        """按 source_ref 读取单个来源 digest，不返回原始全文。"""
        for item in self._load_digests():
            if item.source_ref == source_ref:
                return json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2)
        return json.dumps({"error": f"unknown source_ref: {source_ref}"}, ensure_ascii=False)

    async def read_source_excerpt(
        self,
        source_ref: str,
        query_hint: str = "",
        max_chunks: int = 3,
    ) -> str:
        """按 source_ref 和 query_hint 读取相关原文片段，默认返回最多 3 段。"""
        record = self._load_source_record(source_ref)
        if record is None:
            return json.dumps({"error": f"unknown source_ref: {source_ref}"}, ensure_ascii=False)

        chunks = [SourceChunk.model_validate(item) for item in record.get("chunks", [])]
        excerpts = self._select_excerpts(chunks, query_hint=query_hint, max_chunks=max_chunks)
        return json.dumps(
            [excerpt.model_dump(mode="json") for excerpt in excerpts],
            ensure_ascii=False,
            indent=2,
        )

    async def read_primary_source(self, source_ref: str) -> str:
        """读取主来源的较长关键片段，仍然是受控摘录，不返回整篇全文。"""
        record = self._load_source_record(source_ref)
        if record is None:
            return json.dumps({"error": f"unknown source_ref: {source_ref}"}, ensure_ascii=False)

        chunks = [SourceChunk.model_validate(item) for item in record.get("chunks", [])]
        excerpts = self._select_excerpts(chunks, query_hint="", max_chunks=5)
        return json.dumps(
            [excerpt.model_dump(mode="json") for excerpt in excerpts],
            ensure_ascii=False,
            indent=2,
        )

    def _load_index_entries(self) -> list[SavedSourceIndex]:
        if not self.index_path.exists():
            return []
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [SavedSourceIndex.model_validate(item) for item in data]

    def _load_digests(self) -> list[SourceDigest]:
        if not self.digests_path.exists():
            return []
        data = json.loads(self.digests_path.read_text(encoding="utf-8"))
        return [SourceDigest.model_validate(item) for item in data]

    def _load_source_record(self, source_ref: str) -> dict[str, Any] | None:
        path = self.sources_dir / f"{source_ref}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _select_excerpts(
        self,
        chunks: list[SourceChunk],
        *,
        query_hint: str,
        max_chunks: int,
    ) -> list[SourceExcerpt]:
        normalized_max = max(1, min(max_chunks, 5))
        terms = {
            item
            for item in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", query_hint.lower())
            if len(item) > 1
        }

        scored: list[tuple[float, SourceChunk]] = []
        for chunk in chunks:
            lowered = chunk.text.lower()
            overlap = sum(1 for term in terms if term in lowered)
            numeric_bonus = 1.2 if re.search(r"\d", chunk.text) else 0.0
            early_bonus = max(0.0, 2.0 - (chunk.order * 0.05))
            transcript_bonus = 0.5 if chunk.chunk_type == "transcript" else 0.0
            score = overlap * 3.0 + numeric_bonus + early_bonus + transcript_bonus
            scored.append((score, chunk))

        scored.sort(key=lambda item: (item[0], -item[1].order), reverse=True)
        selected = [chunk for _, chunk in scored[:normalized_max]]
        if not selected:
            return []

        reason = query_hint.strip() or "primary-source"
        return [
            SourceExcerpt(
                source_ref=chunk.source_ref,
                chunk_id=chunk.chunk_id,
                heading=chunk.heading,
                reason=reason,
                text=chunk.text,
            )
            for chunk in selected
        ]


def build_site_queries(
    queries: list[str],
    domains: list[str],
    *,
    max_domains_per_query: int = 3,
    max_total_queries: int | None = None,
) -> list[str]:
    scoped: list[str] = []
    normalized_queries = [query.strip() for query in queries if query.strip()]
    normalized_domains = [domain.strip() for domain in domains if domain.strip()]
    if not normalized_queries or not normalized_domains:
        return scoped

    domain_cursor = 0
    domains_per_query = max(1, min(max_domains_per_query, len(normalized_domains)))

    for query in normalized_queries:
        for _ in range(domains_per_query):
            domain = normalized_domains[domain_cursor % len(normalized_domains)]
            domain_cursor += 1
            scoped.append(f'site:{domain} "{query}"')
            if max_total_queries is not None and len(scoped) >= max_total_queries:
                return scoped
    return scoped


def is_video_candidate(url: str, read_result: ReadPageResult) -> bool:
    all_urls = [url, *read_result.video_urls, *read_result.iframe_urls]
    return any(any(pattern in item for pattern in VIDEO_HOST_PATTERNS) for item in all_urls if item)


def select_best_video_url(read_result: ReadPageResult, page_url: str = "") -> str:
    candidates = [*read_result.video_urls, *read_result.iframe_urls]
    for candidate in candidates:
        if any(pattern in candidate for pattern in VIDEO_HOST_PATTERNS):
            return candidate
    if candidates:
        return candidates[0]
    if page_url and any(pattern in page_url for pattern in VIDEO_HOST_PATTERNS):
        return page_url
    return ""


def score_candidate(
    result: SearchResult,
    read_result: ReadPageResult,
    *,
    wants_video: bool,
) -> float:
    score = 60.0
    score += max(0, 10 - result.rank) * 1.5
    score += min(len(read_result.text) / 500, 20)
    if read_result.author:
        score += 4
    if read_result.published_at:
        score += 4
    if read_result.paywall_status == "public":
        score += 4
    if wants_video and is_video_candidate(result.url, read_result):
        score += 8
    if read_result.engagement_hint:
        score += 4
    return min(score, 100.0)


def collect_source_payload(source: CollectedSource) -> dict[str, Any]:
    return {
        "source_ref": source.ref,
        "source_type": source.source_type,
        "url": source.url,
        "domain": source.domain,
        "title": source.title,
        "author": source.author,
        "published_at": source.published_at,
        "excerpt": source.snippet,
        "quality_score": round(source.quality_score, 1),
        "engagement_hint": source.engagement_hint,
        "paywall_status": source.paywall_status,
        "duration_seconds": source.duration_seconds,
        "transcript_available": bool(source.transcript),
        "text": source.text[:12000],
        "headings": source.headings[:20],
        "paragraphs": source.paragraphs[:40],
        "transcript": source.transcript[:12000],
    }


def is_article_media_domain(netloc: str) -> bool:
    hostname = (netloc or "").lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in ARTICLE_MEDIA_DOMAINS)


def _extract_structure(html: str) -> tuple[list[str], list[str]]:
    """Extract headings and paragraphs from raw HTML."""
    headings = [
        _strip_tags(m.group(1)).strip()
        for m in re.finditer(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S | re.I)
        if _strip_tags(m.group(1)).strip()
    ]
    paragraphs = [
        _strip_tags(m.group(1)).strip()
        for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.S | re.I)
        if _strip_tags(m.group(1)).strip()
    ]
    return headings, paragraphs


def _detect_paywall(html: str) -> bool:
    lowered = html.lower()
    # Only flag strong paywall signals, not generic "subscribe" CTAs
    strong_signals = [
        "sign in to continue",
        "join to continue",
        "member-only",
        "member only",
        "unlock this story",
        "create a free account to continue",
        "subscribe to read",
    ]
    return any(phrase in lowered for phrase in strong_signals)


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _user_agent() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
