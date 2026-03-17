"""Deterministic body injection for TipTap/ProseMirror editors.

Used by image_post and video_post publish agents to reliably inject
body text with newlines, bypassing AI-driven keyboard.type() which
handles \\n inconsistently.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Tool
from pydantic_ai.mcp import MCPServerStdio


def build_body_inject_script(body: str) -> str:
    """Generate a Playwright ``browser_run_code`` script that injects *body*
    into the active TipTap/ProseMirror editor via ``execCommand('insertText')``.

    The body is split on ``\\n`` so that each line becomes a separate paragraph
    in the editor, faithfully preserving the intended line breaks.
    """
    paragraphs = body.split("\n")
    payload_json = json.dumps(paragraphs, ensure_ascii=False)
    return f"""async (page) => {{
  const paragraphs = {payload_json};
  await page.evaluate((lines) => {{
    const editor = document.querySelector('.tiptap.ProseMirror');
    if (!editor) throw new Error('找不到正文编辑器');

    editor.focus();
    document.execCommand('selectAll', false);
    document.execCommand('delete', false);

    for (let i = 0; i < lines.length; i++) {{
      document.execCommand('insertText', false, lines[i]);
      if (i < lines.length - 1) {{
        document.execCommand('insertText', false, '\\n');
      }}
    }}
  }}, paragraphs);
  return {{ ok: true, paragraphs: paragraphs.length }};
}}"""


class BodyInjectTool:
    """Wraps :func:`build_body_inject_script` as a pydantic-ai ``Tool``
    that publish agents can register alongside MCP browser tools.
    """

    def __init__(self, mcp_server: MCPServerStdio):
        self._mcp_server = mcp_server
        self._body: str | None = None
        self._injected = False

    def bind_body(self, body: str) -> None:
        """Bind the body text to inject. Must be called before the agent runs."""
        self._body = body
        self._injected = False

    def get_tool(self) -> Tool:
        return Tool(self.inject_body_content, takes_ctx=False)

    async def inject_body_content(self) -> str:
        """一次性将正文注入到当前页面的 TipTap/ProseMirror 编辑器中（保留换行）。填写正文时必须调用此工具，不要使用 keyboard.type() 或 fill()。"""
        if self._body is None:
            return self._dump({"ok": False, "error": "未绑定正文内容，无法注入"})
        if self._injected:
            return self._dump({"ok": False, "error": "正文已注入过，禁止重复注入"})

        try:
            payload = await self._mcp_server.direct_call_tool(
                name="browser_run_code",
                args={"code": build_body_inject_script(self._body)},
            )
        except Exception as exc:
            return self._dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        self._injected = True
        normalized = self._normalize_payload(payload)
        if isinstance(normalized, dict):
            normalized.setdefault("ok", True)
            return self._dump(normalized)
        return self._dump({"ok": True, "result": normalized})

    # ------------------------------------------------------------------
    # Internal helpers (mirrored from ArticlePublishEditorTools)
    # ------------------------------------------------------------------

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
