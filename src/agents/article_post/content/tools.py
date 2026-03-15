"""Read-only evidence tools for content generation and review."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic_ai import Tool

from ..schemas import SavedSourceIndex, SourceChunk, SourceDigest, SourceExcerpt


class EvidenceReader:
    """Read-only access to research outputs on disk.

    Provides tools for the content generator and accuracy reviewer to look up
    original source material (source index, digests, and raw chunks) without
    any write capability.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.sources_dir = self.base_dir / "research_sources"
        self.digests_path = self.base_dir / "digests.json"
        self.index_path = self.base_dir / "source_index.json"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(self.list_sources, takes_ctx=False),
            Tool(self.read_digest, takes_ctx=False),
            Tool(self.read_excerpt, takes_ctx=False),
            Tool(self.read_full_source, takes_ctx=False),
        ]

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def list_sources(self) -> str:
        """列出所有研究来源的索引信息（source_ref、标题、域名、分块数量等）。"""
        entries = [entry.model_dump(mode="json") for entry in self._load_index_entries()]
        return json.dumps(entries, ensure_ascii=False, indent=2)

    async def read_digest(self, source_ref: str) -> str:
        """按 source_ref 读取来源摘要，包括 summary、key_points、evidence_queries 和 risk_notes。"""
        for item in self._load_digests():
            if item.source_ref == source_ref:
                return json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2)
        return json.dumps({"error": f"unknown source_ref: {source_ref}"}, ensure_ascii=False)

    async def read_excerpt(
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

    async def read_full_source(self, source_ref: str) -> str:
        """读取来源的较长关键片段（最多 5 段），用于深度查阅原始内容。"""
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

    @staticmethod
    def _select_excerpts(
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
