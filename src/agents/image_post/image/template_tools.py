"""Local prompt template directory exploration tools."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic_ai import Tool

TEXT_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".csv",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}


class PromptTemplateDirectoryToolset:
    """Tools that let an agent explore a local prompt-template root directory."""

    def __init__(self, root: Path | str, *, max_file_bytes: int = 512_000):
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max_file_bytes

    def get_tools(self) -> list[Tool]:
        return [
            Tool(self.list_template_roots, takes_ctx=False),
            Tool(self.list_template_dir, takes_ctx=False),
            Tool(self.inspect_template_source, takes_ctx=False),
            Tool(self.search_templates, takes_ctx=False),
            Tool(self.read_template_file, takes_ctx=False),
        ]

    async def list_template_roots(self) -> str:
        """List first-level template sources under the configured template root."""
        if not self.root.exists():
            return self._json({"root": str(self.root), "sources": [], "error": "template root does not exist"})
        if not self.root.is_dir():
            return self._json({"root": str(self.root), "sources": [], "error": "template root is not a directory"})

        sources: list[dict[str, Any]] = []
        for child in sorted(self.root.iterdir(), key=lambda p: p.name.lower()):
            if child.name in SKIP_DIRS:
                continue
            if child.is_dir():
                sources.append(self._source_summary(child))
            elif self._is_text_file(child):
                sources.append(
                    {
                        "name": child.name,
                        "path": child.name,
                        "type": "file",
                        "size_bytes": child.stat().st_size,
                    }
                )
        return self._json({"root": str(self.root), "sources": sources})

    async def list_template_dir(self, path: str = "") -> str:
        """List a directory below the template root without reading full file contents."""
        target = self._resolve_inside_root(path)
        if isinstance(target, str):
            return self._json({"path": path, "entries": [], "error": target})
        if not target.exists():
            return self._json({"path": path, "entries": [], "error": "path does not exist"})
        if not target.is_dir():
            return self._json({"path": self._relative(target), "entries": [], "error": "path is not a directory"})

        entries: list[dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in SKIP_DIRS:
                continue
            item: dict[str, Any] = {
                "name": child.name,
                "path": self._relative(child),
                "type": "directory" if child.is_dir() else "file",
            }
            if child.is_file():
                item["size_bytes"] = child.stat().st_size
                item["text_like"] = self._is_text_file(child)
            entries.append(item)
        return self._json({"path": self._relative(target), "entries": entries})

    async def inspect_template_source(self, path: str = "") -> str:
        """Inspect a template source directory and return structure plus short README excerpts."""
        target = self._resolve_inside_root(path)
        if isinstance(target, str):
            return self._json({"path": path, "error": target})
        if not target.exists():
            return self._json({"path": path, "error": "path does not exist"})
        if target.is_file():
            return await self.read_template_file(path, max_chars=2_000)

        readmes: list[dict[str, Any]] = []
        for name in ("README.md", "README_zh.md", "readme.md", "README.txt"):
            readme = target / name
            if readme.exists() and self._is_text_file(readme):
                content = self._read_text(readme, max_chars=2_000)
                readmes.append({"path": self._relative(readme), "content": content["content"], "truncated": content["truncated"]})

        counts = {"directories": 0, "text_files": 0, "other_files": 0}
        suffixes: dict[str, int] = {}
        examples: list[str] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            root_path = Path(root)
            if root_path != target:
                counts["directories"] += 1
            for filename in files:
                file_path = root_path / filename
                suffix = file_path.suffix.lower() or "<none>"
                suffixes[suffix] = suffixes.get(suffix, 0) + 1
                if self._is_text_file(file_path):
                    counts["text_files"] += 1
                    if len(examples) < 30:
                        examples.append(self._relative(file_path))
                else:
                    counts["other_files"] += 1
            if counts["text_files"] + counts["other_files"] > 2_000:
                break

        return self._json(
            {
                "path": self._relative(target),
                "readmes": readmes,
                "counts": counts,
                "suffixes": dict(sorted(suffixes.items(), key=lambda item: item[0])),
                "text_file_examples": examples,
            }
        )

    async def search_templates(self, query: str, path: str = "", max_results: int = 20) -> str:
        """Search text files below the template root. The agent chooses the query."""
        query = (query or "").strip()
        max_results = max(1, min(int(max_results or 20), 50))
        target = self._resolve_inside_root(path)
        if isinstance(target, str):
            return self._json({"query": query, "results": [], "error": target})
        if not target.exists():
            return self._json({"query": query, "results": [], "error": "path does not exist"})

        terms = self._terms(query)
        files = [target] if target.is_file() else self._iter_text_files(target)
        results: list[dict[str, Any]] = []
        for file_path in files:
            if not self._is_text_file(file_path):
                continue
            text = self._read_text(file_path, max_chars=self.max_file_bytes)["content"]
            score = self._score(text, terms)
            if score <= 0:
                continue
            results.append(
                {
                    "path": self._relative(file_path),
                    "score": score,
                    "snippet": self._snippet(text, terms),
                }
            )

        results.sort(key=lambda item: (-item["score"], item["path"]))
        return self._json({"query": query, "path": self._relative(target), "results": results[:max_results]})

    async def read_template_file(self, path: str, max_chars: int = 8_000) -> str:
        """Read a selected text file below the template root."""
        target = self._resolve_inside_root(path)
        if isinstance(target, str):
            return self._json({"path": path, "error": target})
        if not target.exists():
            return self._json({"path": path, "error": "path does not exist"})
        if not target.is_file():
            return self._json({"path": self._relative(target), "error": "path is not a file"})
        if not self._is_text_file(target):
            return self._json({"path": self._relative(target), "error": "file is not text-like"})
        if target.stat().st_size > self.max_file_bytes:
            max_chars = min(max_chars, 4_000)
        payload = self._read_text(target, max_chars=max(1, min(int(max_chars or 8_000), 30_000)))
        return self._json({"path": self._relative(target), **payload})

    def _source_summary(self, path: Path) -> dict[str, Any]:
        readme = next((path / name for name in ("README.md", "README_zh.md", "readme.md") if (path / name).exists()), None)
        text_files = 0
        dirs = 0
        for root, child_dirs, files in os.walk(path):
            child_dirs[:] = [d for d in child_dirs if d not in SKIP_DIRS]
            dirs += len(child_dirs)
            for filename in files:
                if self._is_text_file(Path(root) / filename):
                    text_files += 1
            if text_files > 500:
                break
        return {
            "name": path.name,
            "path": self._relative(path),
            "type": "directory",
            "has_readme": readme is not None,
            "directory_count": dirs,
            "text_file_count": text_files,
        }

    def _resolve_inside_root(self, path: str) -> Path | str:
        if not self.root.exists():
            return "template root does not exist"
        requested = (path or "").strip().replace("\\", "/")
        target = (self.root / requested).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            return "path is outside template root"
        return target

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix() or "."
        except ValueError:
            return path.as_posix()

    def _iter_text_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for current, dirs, filenames in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for filename in filenames:
                file_path = Path(current) / filename
                if self._is_text_file(file_path):
                    files.append(file_path)
            if len(files) > 5_000:
                break
        return files

    def _is_text_file(self, path: Path) -> bool:
        if not path.is_file():
            return False
        if path.suffix.lower() not in TEXT_SUFFIXES:
            return False
        try:
            return path.stat().st_size <= max(self.max_file_bytes * 4, 1_000_000)
        except OSError:
            return False

    @staticmethod
    def _read_text(path: Path, max_chars: int) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return {"content": raw[:max_chars], "truncated": len(raw) > max_chars, "size_chars": len(raw)}

    @staticmethod
    def _terms(query: str) -> list[str]:
        return [term.lower() for term in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", query) if term.strip()]

    @classmethod
    def _score(cls, text: str, terms: list[str]) -> int:
        if not terms:
            return 1
        lowered = text.lower()
        return sum(lowered.count(term) for term in terms)

    @classmethod
    def _snippet(cls, text: str, terms: list[str], radius: int = 120) -> str:
        if not text:
            return ""
        lowered = text.lower()
        positions = [lowered.find(term) for term in terms if term and lowered.find(term) >= 0]
        pos = min(positions) if positions else 0
        start = max(0, pos - radius)
        end = min(len(text), pos + radius)
        return text[start:end].replace("\n", " ").strip()

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)
