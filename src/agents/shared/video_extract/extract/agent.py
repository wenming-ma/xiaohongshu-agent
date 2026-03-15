"""Agent for extracting real Xiaohongshu video URLs from the current page."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic_ai.mcp import MCPServerStdio

from .....core.base_agent import BaseAgent, ValidationResult
from .....utils.logger import get_logger
from ..schemas import VideoUrlExtractResult

logger = get_logger(__name__)


class ExtractAgent(BaseAgent):
    role = "小红书视频提取员"
    goal = "从当前打开的小红书详情页提取真实视频直链"

    def __init__(self, mcp_server: MCPServerStdio):
        self._mcp_server = mcp_server
        super().__init__()

    def init_tools(self) -> None:
        pass

    def init_agent(self) -> None:
        self._agent = None

    async def forward(self, page_url: str = "") -> VideoUrlExtractResult:
        with self.trace_span("forward"):
            result = await self.step(page_url=page_url)
            validation = await self.validate(result)
            if validation.passed:
                return result
            if not result.error_message:
                result.error_message = validation.feedback
            return result

    async def step(self, page_url: str = "") -> VideoUrlExtractResult:
        expected_page_url = self._normalize_page_url(page_url)
        current_page_url = await self._get_current_page_url()
        if not current_page_url:
            return VideoUrlExtractResult(error_message="无法读取当前页面 URL")

        normalized_current = self._normalize_page_url(current_page_url)
        if expected_page_url and normalized_current != expected_page_url:
            return VideoUrlExtractResult(
                current_page_url=current_page_url,
                error_message="当前页面与目标帖子不一致，请先进入对应详情页后再提取视频",
            )

        candidates = await self._collect_xhs_video_candidates()
        if not candidates:
            return VideoUrlExtractResult(
                current_page_url=current_page_url,
                note_id=self._extract_note_id(current_page_url),
                error_message="当前页未发现真实 mp4 请求，可能视频尚未开始加载",
            )

        return VideoUrlExtractResult(
            success=True,
            video_url=candidates[0][0],
            current_page_url=current_page_url,
            note_id=self._extract_note_id(current_page_url),
            source=candidates[0][1],
        )

    async def validate(self, output: Any) -> ValidationResult:
        if not isinstance(output, VideoUrlExtractResult):
            return ValidationResult.failure("输出类型错误")
        if not output.success:
            return ValidationResult.failure(output.error_message or "未提取到视频直链")
        if not output.video_url.startswith("http"):
            return ValidationResult.failure("提取结果不是有效的直链 URL")
        if ".mp4" not in output.video_url:
            return ValidationResult.failure("提取结果不是 mp4 视频地址")
        return ValidationResult.success()

    async def _get_current_page_url(self) -> str:
        result = await self._mcp_server.direct_call_tool(
            name="browser_evaluate",
            args={"function": "() => location.href"},
        )
        urls = [
            url for url in self._extract_urls_from_payload(result)
            if "xiaohongshu.com/" in url
        ]
        return urls[0] if urls else ""

    async def _collect_xhs_video_candidates(self) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []

        performance_result = await self._mcp_server.direct_call_tool(
            name="browser_evaluate",
            args={
                "function": (
                    "() => performance.getEntriesByType('resource')"
                    ".map((entry) => entry.name)"
                    ".filter((name) => /sns-video.*\\.mp4|xhscdn.*\\.mp4/i.test(name))"
                    ".slice(-20)"
                )
            },
        )
        performance_urls = self._extract_video_urls_from_payload(performance_result)
        candidates.extend((url, "performance") for url in performance_urls)

        network_result = await self._mcp_server.direct_call_tool(
            name="browser_network_requests",
            args={"includeStatic": True},
        )
        network_urls = self._extract_video_urls_from_payload(network_result)
        candidates.extend((url, "network_requests") for url in network_urls)

        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for url, source in candidates:
            if url in seen:
                continue
            seen.add(url)
            deduped.append((url, source))
        return deduped

    @staticmethod
    def _extract_text_fragments(payload: Any) -> list[str]:
        texts: list[str] = []
        if payload is None:
            return texts
        if isinstance(payload, str):
            texts.append(payload)
        elif isinstance(payload, dict):
            for value in payload.values():
                texts.extend(ExtractAgent._extract_text_fragments(value))
        elif isinstance(payload, (list, tuple)):
            for item in payload:
                texts.extend(ExtractAgent._extract_text_fragments(item))
        else:
            for attr in ("text", "content", "markdown", "message"):
                if hasattr(payload, attr):
                    texts.extend(ExtractAgent._extract_text_fragments(getattr(payload, attr)))
        return texts

    @classmethod
    def _extract_urls_from_payload(cls, payload: Any) -> list[str]:
        urls: list[str] = []
        pattern = re.compile(r"https?://[^\s\"'<>\\]+")
        for text in cls._extract_text_fragments(payload):
            normalized = text.replace("\\/", "/")
            urls.extend(match.group(0).rstrip(".,])}") for match in pattern.finditer(normalized))
        return urls

    @classmethod
    def _extract_video_urls_from_payload(cls, payload: Any) -> list[str]:
        urls = cls._extract_urls_from_payload(payload)
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if not re.search(r"sns-video.*\.mp4|xhscdn.*\.mp4", url, re.IGNORECASE):
                continue
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped

    @staticmethod
    def _normalize_page_url(url: str) -> str:
        return urlunsplit(urlsplit((url or "").strip())._replace(query="", fragment="")) if url else ""

    @staticmethod
    def _extract_note_id(url: str) -> str:
        match = re.search(r"/explore/([^/?#]+)|/discovery/item/([^/?#]+)", url or "")
        if not match:
            return ""
        return next(group for group in match.groups() if group)
