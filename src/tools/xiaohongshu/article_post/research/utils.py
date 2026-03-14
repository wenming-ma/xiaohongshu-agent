"""Persistence helpers for article research iterations."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .....utils.logger import get_logger
from ..schemas import SourceChunk
from .state import ResearchState
from .tools import collect_source_payload
from .tools import CollectedSource

logger = get_logger(__name__)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+")


def save_iteration_result(
    state: ResearchState,
    iteration: int,
    *,
    validation_feedback: str = "",
    error_message: str = "",
) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"research_iter_{iteration:02d}_{timestamp}.json"
    output_dir = state.working_dir or state.output_dir or Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / filename

    payload = {
        "topic": state.topic,
        "target_audience": state.target_audience,
        "strategy": state.strategy.value,
        "iteration": iteration,
        "timestamp": timestamp,
        "validation_feedback": validation_feedback,
        "error_message": error_message,
        "brief": _dump_model(state.brief),
        "supervisor_iteration": state.supervisor_iteration,
        "query_plan": state.current_plan.model_dump() if state.current_plan else None,
        "pending_tasks": [_dump_model(task) for task in state.pending_tasks],
        "completed_task_results": [
            _dump_model(task_result) for task_result in state.completed_task_results
        ],
        "current_notes": [_dump_model(note) for note in state.current_notes],
        "aggregated_notes": [_dump_model(note) for note in state.aggregated_notes],
        "candidate_count": len(state.current_candidates),
        "candidates": [
            {"query": query, "result": result.model_dump()}
            for query, result in state.current_candidates
        ],
        "current_task_candidates": {
            task_id: [
                {"query": query, "result": result.model_dump()}
                for query, result in candidates
            ]
            for task_id, candidates in state.current_task_candidates.items()
        },
        "new_collected_count": len(state.current_collected),
        "current_collected_sources": [
            collect_source_payload(source) for source in state.current_collected
        ],
        "current_digest_count": len(state.current_digests),
        "current_digests": [_dump_model(digest) for digest in state.current_digests],
        "total_collected_count": len(state.collected_sources),
        "all_collected_sources": [
            collect_source_payload(source) for source in state.collected_sources
        ],
        "digest_count": len(state.digests_by_source),
        "digests": [_dump_model(digest) for digest in state.digests_by_source.values()],
        "digests_path": state.digests_path,
        "source_index_path": state.source_index_path,
        "evidence_files": state.evidence_files,
        "result": _dump_model(state.current_result),
    }

    filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    state.saved_files.append(str(filepath))
    logger.info("研究轮次 %d 已保存到 %s", iteration, filepath)
    return str(filepath)


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


class SourceChunker:
    def __init__(self, *, max_chunk_chars: int = 520, max_chunks: int = 32):
        self.max_chunk_chars = max_chunk_chars
        self.max_chunks = max_chunks

    def chunk(self, source: CollectedSource) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        order = 0

        for block in self._paragraph_blocks(source):
            chunks.append(
                SourceChunk(
                    chunk_id=f"{source.ref}_p{order + 1:03d}",
                    source_ref=source.ref,
                    chunk_type="paragraph",
                    text=block,
                    order=order,
                )
            )
            order += 1
            if len(chunks) >= self.max_chunks:
                return chunks

        if source.transcript and len(chunks) < self.max_chunks:
            for block in self._split_text(source.transcript):
                chunks.append(
                    SourceChunk(
                        chunk_id=f"{source.ref}_t{order + 1:03d}",
                        source_ref=source.ref,
                        chunk_type="transcript",
                        text=block,
                        order=order,
                    )
                )
                order += 1
                if len(chunks) >= self.max_chunks:
                    break

        if not chunks and source.text.strip():
            chunks.append(
                SourceChunk(
                    chunk_id=f"{source.ref}_p001",
                    source_ref=source.ref,
                    chunk_type="paragraph",
                    text=source.text.strip()[: self.max_chunk_chars],
                    order=0,
                )
            )
        return chunks

    def _paragraph_blocks(self, source: CollectedSource) -> list[str]:
        paragraphs = [item.strip() for item in (source.paragraphs or []) if item and item.strip()]
        if paragraphs:
            blocks: list[str] = []
            current = ""
            for paragraph in paragraphs:
                if len(current) + len(paragraph) + 2 <= self.max_chunk_chars:
                    current = f"{current}\n\n{paragraph}".strip()
                else:
                    if current:
                        blocks.append(current)
                    current = paragraph[: self.max_chunk_chars]
                if len(blocks) >= self.max_chunks:
                    break
            if current and len(blocks) < self.max_chunks:
                blocks.append(current)
            return blocks[: self.max_chunks]
        return self._split_text(source.text)

    def _split_text(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if not normalized:
            return []

        sentences = [item.strip() for item in _SENTENCE_SPLIT_RE.split(normalized) if item.strip()]
        if not sentences:
            sentences = [normalized]

        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= self.max_chunk_chars:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    chunks.append(current)
                current = sentence[: self.max_chunk_chars]
            if len(chunks) >= self.max_chunks:
                break
        if current and len(chunks) < self.max_chunks:
            chunks.append(current)
        return chunks[: self.max_chunks]
