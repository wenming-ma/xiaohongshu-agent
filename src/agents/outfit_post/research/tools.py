"""研究工具模块

包含：
- ImageReaderAgent: 读图（OCR/视觉理解）工具
- PostImageReaderAgent: 帖子图片批量提取+分析工具
- WebSearchAgent: Web搜索工具
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import html as _html
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, parse_qs, unquote, urlunsplit, parse_qsl, urlencode

import httpx
import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent, Tool, BinaryContent

from ..schemas import ImageReadResult, PostImageItem, PostImagesReadResult
from ...shared.utils.image_compression import compress_image_for_review
from ....utils.logger import get_logger
from ....config.settings import RetryConfig, APIConfig, PathConfig
from ....utils.providers import get_text_model, get_google_model
from .prompts import (
    image_reader_system_prompt,
    image_reader_user_prompt,
    post_image_reader_system_prompt,
    post_image_reader_user_prompt,
)

logger = get_logger(__name__)


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


SUPPORTED_IMAGE_SUFFIXES = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
})


# ============================================================================
# ImageReaderAgent
# ============================================================================

class ImageReaderAgent:
    """读图 Agent（输出结构化的 ImageReadResult），并提供 Tool 包装。"""

    def __init__(self):
        self._agent = Agent(
            model=get_google_model(APIConfig.GOOGLE_VISION_MODEL),
            output_type=ImageReadResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_reader_system_prompt(),),
        )

    @staticmethod
    def _error_result(message: str) -> str:
        result = ImageReadResult(
            extracted_text="",
            description="",
            language="unknown",
            has_text=False,
            answer="",
            issues=[message],
        )
        return result.model_dump_json(indent=2)

    async def read_image(self, image_path: str, question: str = "") -> str:
        """
        读取本地截图图片内容（OCR + 轻量理解）。

        只接受浏览器截图或其他本地图片文件，不接受 `.json`、`.txt`、`.md`
        等非图片文件，例如 `research_*.json`。优先把 `browser_take_screenshot`
        生成的图片路径传给此工具。

        Args:
            image_path: 本地图片路径。支持 `.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`
                和 `.gif`。不要传 `research_*.json` 或其他非图片文件。
            question: 可选问题；为空时仅提取图片中的文字和结构化信息。

        Returns:
            ImageReadResult 的 JSON 字符串。即使输入不是有效图片，也会返回带
            `issues` 的结构化结果，而不是抛出异常。
        """
        path = Path(image_path)
        if not path.exists():
            # 截图可能保存在 Playwright downloads 目录
            fallback = PathConfig.DOWNLOADS_DIR / path.name
            if fallback.exists():
                path = fallback
            else:
                return self._error_result(f"图片文件不存在: {image_path}")
        if not path.is_file():
            return self._error_result(f"路径不是文件: {image_path}")
        if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_SUFFIXES))
            return self._error_result(
                f"read_image 只接受图片文件，当前文件类型不支持: {image_path}。"
                f"请传入截图图片路径（{supported}），不要传 .json 或其他文本文件。"
            )

        try:
            image_data = await compress_image_for_review(path, max_size_mb=5.0)
        except Exception as exc:
            logger.warning("ImageReaderAgent: failed to preprocess image %s: %s", path, exc)
            return self._error_result(
                f"图片预处理失败: {type(exc).__name__}: {exc}"
            )

        user_prompt = image_reader_user_prompt(question=(question or "").strip())

        logger.debug("ImageReaderAgent: reading image %s (question=%s)", path.name, bool(question))

        try:
            r = await self._agent.run(
                [
                    user_prompt,
                    BinaryContent(data=image_data, media_type="image/jpeg"),
                ]
            )
        except Exception as exc:
            logger.warning("ImageReaderAgent: model read failed for %s: %s", path, exc)
            return self._error_result(
                f"图片识别失败: {type(exc).__name__}: {exc}"
            )

        return r.output.model_dump_json(indent=2)

    def get_tool(self) -> Tool:
        """获取可供其它 Agent 使用的 Tool。"""
        return Tool(
            self.read_image,
            takes_ctx=False,
            docstring_format='google',
            require_parameter_descriptions=True,
        )


# ============================================================================
# PostImageReaderAgent
# ============================================================================

class PostImageReaderAgent:
    """自主读图 Agent：LLM 自主决策如何提取和分析帖子图片。

    内部运行一个 pydantic-ai Agent，拥有 MCP 浏览器工具和自定义分析工具，
    由 LLM 自主决定提取策略（URL 下载 vs 截屏）和异常处理方式。
    """

    def __init__(self, mcp_server):
        self._mcp_server = mcp_server
        self._vision_semaphore = asyncio.Semaphore(3)

        # 视觉分析 Agent（Google 模型，用于 OCR + 理解）
        self._vision_agent = Agent(
            model=get_google_model(APIConfig.GOOGLE_VISION_MODEL),
            output_type=ImageReadResult,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(image_reader_system_prompt(),),
        )


        # 自定义工具
        custom_tools = [
            Tool(
                self._download_and_analyze,
                takes_ctx=False,
                docstring_format='google',
                require_parameter_descriptions=True,
            ),
            Tool(
                self._analyze_local_image,
                takes_ctx=False,
                docstring_format='google',
                require_parameter_descriptions=True,
            ),
        ]

        # 自主决策 Agent：MCP 浏览器工具 + 自定义分析工具
        self._agent = Agent(
            model=get_text_model(),
            output_type=PostImagesReadResult,
            toolsets=[mcp_server],
            tools=custom_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(post_image_reader_system_prompt(),),
        )

    async def _run_vision_with_limit(self, payload):
        """以受限并发调用 vision model，避免一次性打爆 Gemini 导致 503。"""
        async with self._vision_semaphore:
            return await self._vision_agent.run(payload)

    async def _download_and_analyze(
        self, url: str, index: int, question: str = ""
    ) -> str:
        """下载一张图片 URL 并用视觉模型分析其内容。

        Args:
            url: 图片的 CDN URL（如 https://sns-webpic-qc.xhscdn.com/...）
            index: 图片序号（从 1 开始）
            question: 可选的分析问题；为空时仅提取文字和描述

        Returns:
            PostImageItem 的 JSON 字符串，包含 extracted_text、description 等字段
        """
        try:
            from PIL import Image
            import io

            timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            img = Image.open(io.BytesIO(resp.content))
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)

            user_prompt = image_reader_user_prompt(question=(question or "").strip())
            r = await self._run_vision_with_limit(
                [user_prompt, BinaryContent(data=buf.getvalue(), media_type="image/jpeg")]
            )
            out = r.output
            return PostImageItem(
                index=index, url=url,
                extracted_text=out.extracted_text, description=out.description,
                has_text=out.has_text, issues=out.issues,
            ).model_dump_json(indent=2)

        except Exception as exc:
            logger.warning("PostImageReaderAgent: download_and_analyze %d failed: %s", index, exc)
            return PostImageItem(
                index=index, url=url, issues=[f"下载或分析失败: {exc}"]
            ).model_dump_json(indent=2)

    async def _analyze_local_image(
        self, image_path: str, index: int, question: str = ""
    ) -> str:
        """分析本地图片文件（如截屏）的内容。

        Args:
            image_path: 本地图片文件路径（如 output/playwright-downloads/img-1.png）
            index: 图片序号（从 1 开始）
            question: 可选的分析问题；为空时仅提取文字和描述

        Returns:
            PostImageItem 的 JSON 字符串，包含 extracted_text、description 等字段
        """
        try:
            path = Path(image_path)
            if not path.exists():
                fallback = PathConfig.DOWNLOADS_DIR / path.name
                if fallback.exists():
                    path = fallback
                else:
                    return PostImageItem(
                        index=index, issues=[f"图片文件不存在: {image_path}"]
                    ).model_dump_json(indent=2)

            image_data = await compress_image_for_review(path, max_size_mb=5.0)
            user_prompt = image_reader_user_prompt(question=(question or "").strip())
            r = await self._run_vision_with_limit(
                [user_prompt, BinaryContent(data=image_data, media_type="image/jpeg")]
            )
            out = r.output
            return PostImageItem(
                index=index,
                extracted_text=out.extracted_text, description=out.description,
                has_text=out.has_text, issues=out.issues,
            ).model_dump_json(indent=2)

        except Exception as exc:
            logger.warning("PostImageReaderAgent: analyze_local_image %d failed: %s", index, exc)
            return PostImageItem(
                index=index, issues=[f"截屏分析失败: {exc}"]
            ).model_dump_json(indent=2)

    # ── 主入口 ──

    async def read_post_images(self, question: str = "") -> str:
        """
        提取并分析当前帖子页面中的所有图片内容。

        内部运行自主 Agent，由 LLM 决定如何提取图片（URL 下载或截屏）并分析。
        主 agent 无需关心任何细节，只需消费返回的分析结果。

        Args:
            question: 可选问题；为空时仅提取图片中的文字和结构化信息。

        Returns:
            PostImagesReadResult 的 JSON 字符串，包含每张图片的分析结果。
        """
        prompt = post_image_reader_user_prompt(question=question)

        try:
            result = await self._agent.run(prompt)
            logger.info(
                "PostImageReaderAgent: completed, %d images analyzed",
                len(result.output.images),
            )
            return result.output.model_dump_json(indent=2)
        except Exception as exc:
            logger.error("PostImageReaderAgent: agent run failed: %s", exc)
            return PostImagesReadResult(
                issues=[f"读图 Agent 运行失败: {type(exc).__name__}: {exc}"]
            ).model_dump_json(indent=2)

    def get_tool(self) -> Tool:
        """获取可供其它 Agent 使用的 Tool。"""
        return Tool(
            self.read_post_images,
            takes_ctx=False,
            docstring_format='google',
            require_parameter_descriptions=True,
        )


# ============================================================================
# WebSearchAgent
# ============================================================================

Confidence = Literal["low", "medium", "high"]


class WebSearchExpansionResult(BaseModel):
    """LLM 输出：扩展后的查询集合（用于 deep search）"""
    queries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    notes: str = ""


class WebSearchClaim(BaseModel):
    claim: str
    detail: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class WebSearchSynthesisResult(BaseModel):
    """LLM 输出：整合后的答案（结构化+可追溯来源）"""
    answer: str = ""
    claims: list[WebSearchClaim] = Field(default_factory=list)
    coverage_notes: str = ""


class WebSearchAgent:
    """提供 `web_search` Tool 给其它 Agent 使用。"""

    def __init__(self):
        self._timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        self._serper_keys = _KeyRotator(_load_keys("SERPER_API_KEY"))
        self._tavily_keys = _KeyRotator(_load_keys("TAVILY_API_KEY"))
        self._expander_agent: Agent | None = None
        self._synthesis_agent: Agent | None = None

    async def web_search(self, query: str, max_results: int = 5, deep_search: bool = False) -> str:
        """
        Web 搜索（返回 JSON 字符串，便于 LLM/Tool 消费）。

        Args:
            query: 搜索关键词
            max_results: 最大返回条数
            deep_search: 是否启用 deep search

        Returns:
            JSON 字符串
        """
        q = (query or "").strip()
        max_results = int(max(1, min(max_results or 5, 10)))

        with logfire.span(
            "web_search:call",
            query=q,
            deep_search=bool(deep_search),
            max_results=max_results,
        ) as span:
            if not q:
                span.set_attribute("backend", "none")
                span.set_attribute("results_count", 0)
                span.set_attribute("error", "empty query")
                return json.dumps(
                    {
                        "query": query,
                        "deep_search": bool(deep_search),
                        "backend": "none",
                        "results": [],
                        "answer": "",
                        "claims": [],
                        "coverage_notes": "empty query",
                        "error": "empty query",
                    },
                    ensure_ascii=False,
                )

            error: str = ""
            backend: str = "unknown"
            results: list[dict[str, str]] = []
            debug: dict[str, Any] | None = None

            try:
                if deep_search:
                    backend, results, debug = await self._deep_search(q, max_results=max_results)
                else:
                    one = await self._search_once(q, max_results=max_results)
                    backend = one.get("backend", "unknown")
                    results = one.get("results") or []
                    error = one.get("error") or ""

            except Exception as e:
                error = self._format_error(e)
                logger.warning("WebSearchAgent search pipeline failed: %s", error)

            normalized_results: list[dict[str, str]] = []
            for item in results:
                url = (item.get("url") or "").strip()
                normalized_results.append(
                    {
                        "title": (item.get("title") or "").strip(),
                        "url": self._canonicalize_url(url) or url,
                        "snippet": (item.get("snippet") or "").strip(),
                    }
                )
            results = normalized_results

            span.set_attribute("backend", backend)
            span.set_attribute("results_count", len(results))
            if error:
                span.set_attribute("error", error)

            if not results and backend.startswith("duckduckgo") and not error:
                msg = (
                    "duckduckgo returned empty results; consider setting SERPER_API_KEY or TAVILY_API_KEY "
                    "for more reliable SERP results"
                )
                logfire.warn(msg, backend=backend)

            answer = ""
            claims: list[dict[str, Any]] = []
            coverage_notes = ""

            try:
                synth = await self._synthesize(q, results)
                answer = (synth.answer or "").strip()
                coverage_notes = (synth.coverage_notes or "").strip()

                allowed_urls = {r.get("url", "") for r in results if r.get("url")}
                cleaned: list[dict[str, Any]] = []
                for c in synth.claims or []:
                    srcs = [s for s in (c.sources or []) if s in allowed_urls]
                    if not srcs:
                        continue
                    cleaned.append(
                        {
                            "claim": (c.claim or "").strip(),
                            "detail": (c.detail or "").strip(),
                            "sources": srcs,
                            "confidence": c.confidence,
                        }
                    )
                claims = cleaned
            except Exception as e:
                synth_err = self._format_error(e)
                logger.warning("WebSearchAgent synthesis failed: %s", synth_err)
                error = (error + " | " + synth_err).strip(" |")
                span.set_attribute("error", error)

            payload: dict[str, Any] = {
                "query": q,
                "deep_search": bool(deep_search),
                "backend": backend,
                "results": results,
                "answer": answer,
                "claims": claims,
                "coverage_notes": coverage_notes,
                "error": error,
            }
            if debug is not None:
                payload["debug"] = debug

            return json.dumps(payload, ensure_ascii=False)

    async def _search_serper(self, query: str, max_results: int, api_key: str) -> dict[str, Any]:
        """Google Serper（需要 SERPER_API_KEY）"""
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": max_results}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post("https://google.serper.dev/search", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()

        results = []
        for item in (data.get("organic") or [])[:max_results]:
            results.append(
                {
                    "title": item.get("title") or "",
                    "url": item.get("link") or "",
                    "snippet": item.get("snippet") or "",
                }
            )

        return {"query": query, "backend": "serper", "results": results, "error": ""}

    async def _search_tavily(self, query: str, max_results: int, api_key: str) -> dict[str, Any]:
        """Tavily（需要 TAVILY_API_KEY）"""
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post("https://api.tavily.com/search", json=payload)
            r.raise_for_status()
            data = r.json()

        results = []
        for item in (data.get("results") or [])[:max_results]:
            results.append(
                {
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "snippet": item.get("content") or "",
                }
            )

        return {"query": query, "backend": "tavily", "results": results, "error": ""}

    async def _search_duckduckgo_instant_answer(self, query: str, max_results: int) -> dict[str, Any]:
        """DuckDuckGo Instant Answer API（无需 key）"""
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "no_redirect": "1",
            "skip_disambig": "1",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get("https://api.duckduckgo.com/", params=params)
            r.raise_for_status()
            data = r.json()

        results: list[dict[str, str]] = []

        abstract = (data.get("AbstractText") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        heading = (data.get("Heading") or "").strip()
        if abstract or abstract_url:
            results.append(
                {
                    "title": heading or query,
                    "url": abstract_url,
                    "snippet": abstract,
                }
            )

        def _collect_related(items: list[Any]) -> None:
            for it in items:
                if isinstance(it, dict) and "Topics" in it:
                    _collect_related(it.get("Topics") or [])
                elif isinstance(it, dict):
                    text = (it.get("Text") or "").strip()
                    url = (it.get("FirstURL") or "").strip()
                    if text or url:
                        results.append({"title": text or query, "url": url, "snippet": text})

        _collect_related(data.get("RelatedTopics") or [])

        seen = set()
        deduped: list[dict[str, str]] = []
        for item in results:
            key = (item.get("url") or "") + "|" + (item.get("title") or "")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max_results:
                break

        return {"query": query, "backend": "duckduckgo_instant_answer", "results": deduped, "error": ""}

    async def _search_duckduckgo_html(self, query: str, max_results: int) -> dict[str, Any]:
        """DuckDuckGo HTML SERP（无需 key）"""
        params = {"q": query}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        }

        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            r = await client.get("https://html.duckduckgo.com/html/", params=params)
            r.raise_for_status()
            text = r.text

        if self._ddg_html_is_anomaly(text):
            err = (
                "duckduckgo_html blocked by anomaly/challenge page; configure SERPER_API_KEY or TAVILY_API_KEY "
                "for reliable results"
            )
            logger.warning("DuckDuckGo HTML blocked for query=%r", query)
            logfire.warn("duckduckgo_html_blocked", query=query)
            return {"query": query, "backend": "duckduckgo_html", "results": [], "error": err}

        def _strip_tags(s: str) -> str:
            s = re.sub(r"<[^>]+>", "", s)
            return _html.unescape(s).strip()

        def _decode_ddg_href(href: str) -> str:
            try:
                parts = urlsplit(href)
                qs = parse_qs(parts.query)
                if "uddg" in qs and qs["uddg"]:
                    return unquote(qs["uddg"][0])
            except Exception:
                pass
            return href

        results: list[dict[str, str]] = []

        pat = re.compile(
            r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>([\s\S]*?)</a>'
            r'[\s\S]*?'
            r'<a class="result__snippet" href="[^"]*"[^>]*>([\s\S]*?)</a>',
            re.IGNORECASE,
        )
        for m in pat.finditer(text):
            href = _decode_ddg_href(m.group(1))
            title = _strip_tags(m.group(2))
            snippet = _strip_tags(m.group(3))
            if title or href or snippet:
                results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= max_results:
                break

        return {"query": query, "backend": "duckduckgo_html", "results": results, "error": ""}

    @staticmethod
    def _ddg_html_is_anomaly(html_text: str) -> bool:
        if not html_text:
            return False
        s = html_text.lower()
        return (
            "anomaly-modal" in s
            or "challenge-form" in s
            or "duckduckgo.com/anomaly.js" in s
            or "anomaly.js" in s
        )

    async def _search_once(self, query: str, max_results: int) -> dict[str, Any]:
        """执行一次搜索（按可用后端选择，支持 key 轮换与 exhaustion）"""
        serper_key = self._serper_keys.next()
        if serper_key:
            try:
                return await self._search_serper(query, max_results=max_results, api_key=serper_key)
            except httpx.HTTPStatusError as exc:
                logger.warning("Serper search failed: %s", exc)
                if exc.response.status_code in (400, 401, 403, 429):
                    self._serper_keys.mark_exhausted(serper_key)
            except Exception as exc:
                logger.warning("Serper search failed: %s", exc)

        tavily_key = self._tavily_keys.next()
        if tavily_key:
            try:
                return await self._search_tavily(query, max_results=max_results, api_key=tavily_key)
            except httpx.HTTPStatusError as exc:
                logger.warning("Tavily search failed: %s", exc)
                if exc.response.status_code in (401, 403, 429, 432):
                    self._tavily_keys.mark_exhausted(tavily_key)
            except Exception as exc:
                logger.warning("Tavily search failed: %s", exc)

        data = await self._search_duckduckgo_instant_answer(query, max_results=max_results)
        if not (data.get("results") or []):
            data = await self._search_duckduckgo_html(query, max_results=max_results)
        return data

    def _get_expander_agent(self) -> Agent:
        if self._expander_agent is None:
            system_prompt = (
                "You expand a web search query into multiple diverse, high-signal queries.\n"
                "Return ONLY structured data via the output schema.\n"
                "Rules:\n"
                "- Include the original query.\n"
                "- Produce paraphrases + facet queries + multi-language (zh/en) variants.\n"
                "- Keep queries short and search-engine friendly.\n"
                "- Avoid adding URLs or tracking tokens.\n"
            )
            self._expander_agent = Agent(
                model=get_text_model(),
                output_type=WebSearchExpansionResult,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,
                system_prompt=(system_prompt,),
            )
        return self._expander_agent

    def _get_synthesis_agent(self) -> Agent:
        if self._synthesis_agent is None:
            system_prompt = (
                "You are an information synthesis assistant.\n"
                "Given ONLY a user query and a list of search results (title/url/snippet),\n"
                "produce a detailed, accurate answer with structured claims.\n"
                "Hard rules:\n"
                "- Every claim MUST include 1+ sources that are EXACTLY URLs from the provided results.\n"
                "- If evidence is weak or missing, say so and lower confidence.\n"
                "- Do NOT paste long webpage content; synthesize succinctly.\n"
            )
            self._synthesis_agent = Agent(
                model=get_text_model(),
                output_type=WebSearchSynthesisResult,
                instrument=True,
                retries=RetryConfig.AGENT_RETRIES,
                system_prompt=(system_prompt,),
            )
        return self._synthesis_agent

    async def _synthesize(self, query: str, results: list[dict[str, str]]) -> WebSearchSynthesisResult:
        """把搜索结果整合为答案"""
        urls = [r.get("url", "") for r in results if r.get("url")]
        prompt = (
            f"User query:\n{query}\n\n"
            f"Allowed URLs (MUST use these for sources):\n{json.dumps(urls, ensure_ascii=False, indent=2)}\n\n"
            f"Search results (use ONLY these snippets as evidence):\n"
            f"{json.dumps(results, ensure_ascii=False, indent=2)}\n\n"
            "Return:\n"
            "- answer: concise but helpful\n"
            "- claims: multiple detailed claims; each with sources and confidence\n"
            "- coverage_notes: what is well-supported vs uncertain\n"
        )
        r = await self._get_synthesis_agent().run(prompt)
        return r.output

    @staticmethod
    def _format_error(e: Exception) -> str:
        msg = str(e).strip()
        if not msg:
            msg = repr(e)
        return f"{type(e).__name__}: {msg}"

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """URL 规范化：去掉 fragment，移除常见追踪参数"""
        if not url:
            return ""
        try:
            parts = urlsplit(url)
            scheme = parts.scheme or "https"
            netloc = parts.netloc
            path = parts.path or ""
            if not netloc and parts.path.startswith("//"):
                p2 = urlsplit("https:" + url)
                scheme, netloc, path, parts = p2.scheme, p2.netloc, p2.path, p2

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
            for k, v in parse_qsl(parts.query, keep_blank_values=False):
                if k in drop_keys:
                    continue
                if k.startswith("utm_"):
                    continue
                kept.append((k, v))
            query2 = urlencode(kept, doseq=True)
            return urlunsplit((scheme, netloc, path, query2, ""))
        except Exception:
            return url.split("#", 1)[0]

    @classmethod
    def _merge_rank_results(
        cls,
        per_query_results: dict[str, dict[str, Any]],
        max_results: int,
    ) -> list[dict[str, str]]:
        """合并多个 query 的搜索结果"""
        agg: dict[str, dict[str, Any]] = {}
        for q, payload in per_query_results.items():
            res_list: list[dict[str, str]] = payload.get("results") or []
            for idx, item in enumerate(res_list):
                url = item.get("url", "")
                canon = cls._canonicalize_url(url) or url
                if not canon:
                    continue
                cur = agg.get(canon)
                if cur is None:
                    agg[canon] = {
                        "url": canon,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "coverage": 1,
                        "pos_sum": idx,
                        "pos_cnt": 1,
                        "best_pos": idx,
                        "queries": {q},
                    }
                else:
                    if q not in cur["queries"]:
                        cur["queries"].add(q)
                        cur["coverage"] += 1
                    cur["pos_sum"] += idx
                    cur["pos_cnt"] += 1
                    cur["best_pos"] = min(cur["best_pos"], idx)

        ranked = sorted(
            agg.values(),
            key=lambda x: (-x["coverage"], x["best_pos"], (x["pos_sum"] / max(1, x["pos_cnt"]))),
        )
        out: list[dict[str, str]] = []
        for item in ranked[:max_results]:
            out.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
        return out

    async def _search_many(self, queries: list[str], per_query_k: int) -> dict[str, dict[str, Any]]:
        """并发执行多个搜索"""
        sem = asyncio.Semaphore(3)

        async def _run(qx: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                try:
                    data = await self._search_once(qx, max_results=per_query_k)
                    return qx, {
                        "backend": data.get("backend", ""),
                        "results": data.get("results") or [],
                        "error": data.get("error") or "",
                    }
                except Exception as e:
                    return qx, {"backend": "error", "results": [], "error": self._format_error(e)}

        pairs = await asyncio.gather(*[_run(qx) for qx in queries])
        return {k: v for k, v in pairs}

    async def _deep_search(self, query: str, max_results: int) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
        """Deep search：扩写 query → 多轮搜索 → 合并/去重/排序"""
        rounds = 2
        per_query_k = min(5, max_results)
        debug: dict[str, Any] = {"rounds": rounds, "expanded_queries": [], "per_query": {}}

        try:
            prompt1 = (
                f"Original query: {query}\n\n"
                "Generate 6-10 search queries.\n"
                "- Include zh and en variants.\n"
                "- Include paraphrases and facet queries.\n"
                "- Keep each query short.\n"
            )
            r1 = await self._get_expander_agent().run(prompt1)
            expanded = [s.strip() for s in (r1.output.queries or []) if str(s).strip()]
        except Exception as e:
            debug["expand_error_round1"] = self._format_error(e)
            expanded = [query]

        if query not in expanded:
            expanded.insert(0, query)
        expanded = expanded[:10]

        per_query = await self._search_many(expanded, per_query_k=per_query_k)

        try:
            top_context: list[dict[str, str]] = []
            for qx, payload in per_query.items():
                for item in (payload.get("results") or [])[:2]:
                    top_context.append(
                        {
                            "query": qx,
                            "title": item.get("title", ""),
                            "snippet": item.get("snippet", ""),
                            "url": item.get("url", ""),
                        }
                    )
                if len(top_context) >= 10:
                    break
            prompt2 = (
                f"Original query: {query}\n\n"
                f"Seed context (top snippets):\n{json.dumps(top_context, ensure_ascii=False, indent=2)}\n\n"
                "Generate 4-6 additional facet queries (zh/en) to cover missing angles.\n"
                f"Existing queries:\n{json.dumps(expanded, ensure_ascii=False, indent=2)}\n"
            )
            r2 = await self._get_expander_agent().run(prompt2)
            extra = [s.strip() for s in (r2.output.queries or []) if str(s).strip()]
            extra = [q2 for q2 in extra if q2 not in expanded]
            extra = extra[:6]
        except Exception as e:
            debug["expand_error_round2"] = self._format_error(e)
            extra = []

        expanded_all = expanded + extra
        debug["expanded_queries"] = expanded_all

        if extra:
            per_query2 = await self._search_many(extra, per_query_k=per_query_k)
            per_query.update(per_query2)

        for qx, payload in per_query.items():
            debug["per_query"][qx] = {
                "backend": payload.get("backend", ""),
                "count": len(payload.get("results") or []),
                "error": payload.get("error") or "",
            }

        merged = self._merge_rank_results(per_query, max_results=max_results)

        backends = {payload.get("backend", "") for payload in per_query.values() if payload.get("backend")}
        backend = backends.pop() if len(backends) == 1 else "mixed"
        return backend, merged, debug

    def get_tool(self) -> Tool:
        """获取可供其它 Agent 使用的 Tool。"""
        return Tool(self.web_search, takes_ctx=False)
