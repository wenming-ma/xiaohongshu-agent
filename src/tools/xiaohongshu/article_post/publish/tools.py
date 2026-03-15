"""Deterministic publish tools for the long-form editor."""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Tool
from pydantic_ai.mcp import MCPServerStdio

from ..schemas import XHSArticleContent
from .utils import build_editor_script, build_slot_cleanup_script


class ArticlePublishEditorTools:
    """Small toolset that hides fixed editor scripts behind semantic tools."""

    def __init__(self, mcp_server: MCPServerStdio):
        self._mcp_server = mcp_server
        self._content: XHSArticleContent | None = None
        self._content_injected = False

    def bind_content(self, content: XHSArticleContent) -> None:
        self._content = content
        self._content_injected = False

    def get_tools(self) -> list[Tool]:
        return [
            Tool(self.inject_article_content, takes_ctx=False),
            Tool(self.cleanup_image_slots, takes_ctx=False),
        ]

    async def inject_article_content(self) -> str:
        """向当前长文编辑器一次性注入标题、正文和 `[IMAGE_SLOT:xxx]` 槽位标记。只在进入写长文编辑器后调用，且必须先于图片上传。"""
        if self._content is None:
            return self._dump({"ok": False, "error": "未绑定文章内容，无法注入正文"})
        if self._content_injected:
            return self._dump({"ok": False, "error": "本轮正文已经注入过，禁止重复注入以免覆盖已插入内容"})

        try:
            payload = await self._mcp_server.direct_call_tool(
                name="browser_run_code",
                args={"code": build_editor_script(self._content)},
            )
        except Exception as exc:
            return self._dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        normalized = self._normalize_payload(payload)
        self._content_injected = True
        if isinstance(normalized, dict):
            normalized.setdefault("ok", True)
            return self._dump(normalized)
        return self._dump({"ok": True, "result": normalized})

    async def cleanup_image_slots(self) -> str:
        """清理正文里残留的 `[IMAGE_SLOT:xxx]` 槽位段落。只在所有图片都插完之后调用。"""
        try:
            payload = await self._mcp_server.direct_call_tool(
                name="browser_run_code",
                args={"code": build_slot_cleanup_script()},
            )
        except Exception as exc:
            return self._dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        normalized = self._normalize_payload(payload)
        if isinstance(normalized, list):
            return self._dump({"ok": True, "removed": normalized})
        if isinstance(normalized, dict):
            normalized.setdefault("ok", True)
            return self._dump(normalized)
        return self._dump({"ok": True, "result": normalized})

    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def _normalize_payload(cls, payload: Any) -> Any:
        texts = cls._extract_text_fragments(payload)
        if len(texts) == 1:
            candidate = texts[0].strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return candidate
        if texts:
            return "\n".join(fragment for fragment in texts if fragment.strip())
        return payload

    @classmethod
    def _extract_text_fragments(cls, payload: Any) -> list[str]:
        texts: list[str] = []
        if payload is None:
            return texts
        if isinstance(payload, str):
            texts.append(payload)
            return texts
        if isinstance(payload, dict):
            if isinstance(payload.get("text"), str):
                texts.append(payload["text"])
                return texts
            for value in payload.values():
                texts.extend(cls._extract_text_fragments(value))
            return texts
        if isinstance(payload, (list, tuple)):
            for item in payload:
                texts.extend(cls._extract_text_fragments(item))
            return texts
        for attr in ("text", "content", "message"):
            if hasattr(payload, attr):
                texts.extend(cls._extract_text_fragments(getattr(payload, attr)))
        return texts


def create_article_publish_tools(mcp_server: MCPServerStdio) -> ArticlePublishEditorTools:
    return ArticlePublishEditorTools(mcp_server)
