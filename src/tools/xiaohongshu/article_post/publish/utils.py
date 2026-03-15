"""Helpers for deterministic long-form editor injection."""

from __future__ import annotations

import json

from ..schemas import ArticleBlockType, XHSArticleContent

IMAGE_SLOT_PREFIX = "[IMAGE_SLOT:"
IMAGE_SLOT_SUFFIX = "]"


def build_editor_script(content: XHSArticleContent) -> str:
    payload = {
        "title": content.title,
        "blocks": _build_editor_blocks(content),
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""async (page) => {{
  const payload = {payload_json};
  const titleInput = page.locator('textarea.d-text').first();
  await titleInput.fill(payload.title);
  await page.evaluate((data) => {{
    const editor = document.querySelector('.tiptap.ProseMirror');
    if (!editor) throw new Error('找不到长文编辑器');

    const clearEditor = () => {{
      editor.focus();
      document.execCommand('selectAll', false);
      document.execCommand('delete', false);
    }};

    const insertText = (text) => {{
      editor.focus();
      document.execCommand('insertText', false, text);
    }};

    clearEditor();
    for (const block of data.blocks) {{
      if (block.type === 'text') {{
        insertText(`${{block.text}}\\n`);
      }} else if (block.type === 'slot') {{
        insertText(`{IMAGE_SLOT_PREFIX}${{block.key}}{IMAGE_SLOT_SUFFIX}\\n`);
      }}
    }}
  }}, payload);
  return {{
    title: payload.title,
    slotKeys: payload.blocks.filter((block) => block.type === 'slot').map((block) => block.key),
  }};
}}"""


def build_slot_cleanup_script() -> str:
    return """async (page) => {
  return await page.evaluate(() => {
    const removed = [];
    const paragraphs = Array.from(document.querySelectorAll('.tiptap.ProseMirror p'));
    for (const paragraph of paragraphs) {
      const text = (paragraph.textContent || '').trim();
      if (/^\\[IMAGE_SLOT:[^\\]]+\\]$/.test(text)) {
        removed.push(text);
        paragraph.remove();
      }
    }
    return removed;
  });
}"""


def _build_editor_blocks(content: XHSArticleContent) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []

    def append_text(value: str) -> None:
        text = value.strip()
        if text:
            blocks.append({"type": "text", "text": text})

    append_text(content.lead)
    append_text(content.attribution_line)

    for section in content.sections:
        append_text(section.heading)
        append_text(section.summary)
        for block in section.blocks:
            if block.block_type == ArticleBlockType.IMAGE_SLOT and block.image_key:
                blocks.append({"type": "slot", "key": block.image_key})
                continue
            append_text(_render_block_text(block))

    closing = content.closing.strip()
    if closing and (not blocks or blocks[-1].get("text") != closing):
        blocks.append({"type": "text", "text": closing})

    return blocks


def _render_block_text(block: object) -> str:
    block_type = getattr(block, "block_type", None)
    text = getattr(block, "text", "").strip()
    items = [item.strip() for item in getattr(block, "items", []) if item.strip()]

    if block_type in (ArticleBlockType.HEADING, ArticleBlockType.PARAGRAPH) and text:
        return text
    if block_type == ArticleBlockType.QUOTE and text:
        return f"「{text}」"
    if block_type == ArticleBlockType.BULLET_LIST:
        return "\n".join(f"- {item}" for item in items)
    if block_type == ArticleBlockType.NUMBERED_LIST:
        return "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, start=1))
    return ""
