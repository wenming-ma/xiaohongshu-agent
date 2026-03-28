import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from pydantic_ai.messages import ModelMessage

from ...shared.utils.message_history import truncate_history_by_rounds
from ..schemas import VideoResearchResult, Platform


@dataclass
class ResearchState:
    topic: str
    platforms: List[Platform]
    max_videos: int
    output_dir: Path | None

    message_history: list[ModelMessage] = field(default_factory=list)
    current_result: VideoResearchResult | None = None
    last_feedback: str | None = None
    seen_urls: set[str] = field(default_factory=set)
    all_keywords: list[str] = field(default_factory=list)
    last_duplicate_urls: list[str] = field(default_factory=list)

    _KEYWORD_STOP_WORDS = {
        "tutorial",
        "guide",
        "review",
        "vlog",
        "tips",
        "tip",
        "mistakes",
        "routine",
        "comparison",
        "compare",
        "beginner",
        "beginners",
        "honest",
        "before",
        "after",
        "step",
        "by",
        "local",
        "full",
        "how",
        "to",
    }

    def record_result(self, result: VideoResearchResult) -> None:
        deduped_sources = []
        duplicate_urls: list[str] = []
        current_batch_urls: set[str] = set()

        for source in result.sources:
            url = (source.url or "").strip()
            if not url:
                continue
            if url in current_batch_urls or url in self.seen_urls:
                duplicate_urls.append(url)
                continue
            current_batch_urls.add(url)
            deduped_sources.append(source)

        result.sources = deduped_sources
        self.seen_urls.update(current_batch_urls)
        self.last_duplicate_urls = self._unique_keep_order(duplicate_urls)[:8]

        cleaned_keywords = self._clean_keywords(result.keywords)
        result.keywords = cleaned_keywords
        seen_keyword_values = {item.lower() for item in self.all_keywords}
        for keyword in cleaned_keywords:
            lowered = keyword.lower()
            if lowered in seen_keyword_values:
                continue
            self.all_keywords.append(keyword)
            seen_keyword_values.add(lowered)

    def inject_feedback(self, feedback: str) -> None:
        keywords = self.current_result.keywords if self.current_result else []
        duplicate_urls = self.last_duplicate_urls
        missing_platforms = self._missing_platform_names()
        suggested_keywords = self._suggest_next_keywords(keywords or self.all_keywords)
        keyword_text = "、".join(keywords or self.all_keywords) or "（上一轮没有明确返回 keywords，请这轮务必补全）"
        duplicate_text = "\n".join(f"- {url}" for url in duplicate_urls) or "- 暂无重复 URL 记录"
        missing_platform_text = "、".join(missing_platforms) or "无"
        suggestion_text = "\n".join(f"- {keyword}" for keyword in suggested_keywords) or (
            "- change search intent bucket entirely (tutorial / mistakes / routine / honest review / comparison)\n"
            "- use at least 4 fresh English queries this round"
        )

        self.last_feedback = f"""{feedback}

### Search Memory (Do Not Ignore)
- Already used English queries: {keyword_text}
- Missing platform coverage: {missing_platform_text}
- Duplicate URLs seen in the latest round:
{duplicate_text}

### Next Actions Required
1. Do NOT reuse the duplicate URLs above. Open new results only.
2. This round must use at least 4 fresh ENGLISH queries, and they must come from different intent buckets.
3. Do not just append the same suffix repeatedly. Switch search intent: tutorial / mistakes / routine / comparison / honest review / local guide / beginner.
4. If one platform keeps returning repetitive results, change both the keyword and the page section you browse (Videos, Explore, Trending, recent results).
5. Scroll deeper after changing the query; do not stop at the first visible results.
6. Return the actual English queries you used in the `keywords` field.

### Suggested New Query Angles
{suggestion_text}

IMPORTANT: Use natural browsing behavior, not direct search URLs.
"""
        self.last_feedback = self.last_feedback.strip()

    def _missing_platform_names(self) -> list[str]:
        if self.current_result is None:
            return []
        found = {source.platform.value for source in self.current_result.sources}
        return [platform.value for platform in self.platforms if platform.value not in found]

    def _suggest_next_keywords(self, keywords: list[str]) -> list[str]:
        used = {keyword.lower() for keyword in keywords}
        bases = self._keyword_bases(keywords)
        suffixes = [
            "tutorial",
            "guide",
            "mistakes",
            "tips",
            "routine",
            "honest review",
            "comparison",
            "beginner",
            "local guide",
            "before after",
        ]

        suggestions: list[str] = []
        seen_suggestions: set[str] = set()
        for base in bases[:4]:
            for suffix in suffixes:
                candidate = f"{base} {suffix}".strip()
                lowered = candidate.lower()
                if lowered in used or lowered in seen_suggestions:
                    continue
                suggestions.append(candidate)
                seen_suggestions.add(lowered)
                if len(suggestions) >= 6:
                    return suggestions
        return suggestions

    def _keyword_bases(self, keywords: list[str]) -> list[str]:
        bases: list[str] = []
        for keyword in keywords:
            tokens = [
                token for token in re.split(r"[^a-zA-Z0-9]+", keyword.lower())
                if token and token not in self._KEYWORD_STOP_WORDS
            ]
            base = " ".join(tokens).strip()
            if not base:
                base = keyword.strip().lower()
            if base and base not in bases:
                bases.append(base)
        return bases

    @staticmethod
    def _clean_keywords(keywords: list[str]) -> list[str]:
        return ResearchState._unique_keep_order(keywords)

    @staticmethod
    def _unique_keep_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw in values:
            value = str(raw).strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(value)
        return result

    def get_recent_history(self, max_rounds: int) -> list[ModelMessage]:
        """保留首轮 + 最近若干完整轮次，并确保 tool call / return 成对存在。"""
        return truncate_history_by_rounds(
            self.message_history,
            max_rounds=max_rounds,
            keep_first_round=True,
        )
