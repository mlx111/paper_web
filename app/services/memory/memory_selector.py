"""
MemorySelector — semantic memory selection.

Mirrors Claude Code's findRelevantMemories: scan MEMORY.md index,
use a cheap/fast model to pick up to 5 most relevant memories,
then load only those files into context.

This avoids the O(n) full-load-and-embed approach.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from .memory_index import MemoryIndex
from .memory_types import MemoryEntry


SELECT_PROMPT = """You are selecting memories that will help process a user's query.

You will be given:
1. The user's query
2. A list of available memory files with their descriptions

Return ONLY a comma-separated list of filenames (up to 5) for memories
that are clearly useful for processing the query. Rules:
- Include only memories you are CERTAIN will be helpful.
- If unsure, do NOT include it.
- If none are relevant, return "NONE".
- Do NOT include memories that reference tools already being used.
- DO include memories with warnings, gotchas, or known issues.

Format: filename1.md, filename2.md
"""

# Fallback keyword matching when no LLM is available
_MATCH_WEIGHTS: dict[str, float] = {
    "user": 0.8,
    "feedback": 1.0,  # Always check feedback first
    "project": 0.7,
    "reference": 0.6,
}


class MemorySelector:
    """Selects relevant memories for a query."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.index = MemoryIndex(storage_dir)

    # ---- Public API ----

    async def select(
        self,
        query: str,
        *,
        max_results: int = 5,
        llm_call: Any = None,
    ) -> list[MemoryEntry]:
        """
        Select up to max_results relevant memories for the query.

        If llm_call is provided, use semantic selection.
        Otherwise fall back to keyword matching.
        """
        indexed = self.index.read_index()
        if not indexed:
            return []

        if llm_call is not None:
            return await self._select_llm(query, indexed, max_results, llm_call)

        return self._select_keyword(query, indexed, max_results)

    def select_sync(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> list[MemoryEntry]:
        """Synchronous version — uses keyword matching only."""
        indexed = self.index.read_index()
        if not indexed:
            return []
        return self._select_keyword(query, indexed, max_results)

    # ---- LLM-based selection ----

    async def _select_llm(
        self,
        query: str,
        indexed: list[dict[str, str]],
        max_results: int,
        llm_call: Any,
    ) -> list[MemoryEntry]:
        """Use a cheap LLM to pick the most relevant memories."""
        # Build the candidate list
        candidates = []
        for entry in indexed:
            candidates.append(
                f"- {entry['filename']}: {entry['title']} — {entry['description']}"
            )

        if not candidates:
            return []

        user_message = (
            f"Query: {query}\n\n"
            f"Available memories:\n" + "\n".join(candidates)
        )

        try:
            messages = [
                {"role": "system", "content": SELECT_PROMPT},
                {"role": "user", "content": user_message},
            ]
            response = await llm_call(messages, max_tokens=100)
            response_text = (response or "").strip()
        except Exception:
            return self._select_keyword(query, indexed, max_results)

        if response_text.upper() == "NONE" or not response_text:
            return []

        # Parse comma-separated filenames
        filenames = [f.strip() for f in response_text.split(",")]
        filenames = [f for f in filenames if f.endswith(".md")]

        # Load selected memories
        entries: list[MemoryEntry] = []
        seen: set[str] = set()
        for fname in filenames[:max_results]:
            if fname in seen:
                continue
            seen.add(fname)
            entry = self._load_by_filename(fname)
            if entry is not None:
                entries.append(entry)

        return entries

    # ---- Keyword-based fallback ----

    def _select_keyword(
        self,
        query: str,
        indexed: list[dict[str, str]],
        max_results: int,
    ) -> list[MemoryEntry]:
        """Simple keyword-relevance matching."""
        query_lower = query.lower()
        query_terms = set(re.findall(r"\w+", query_lower))

        scored: list[tuple[float, dict[str, str]]] = []
        for entry in indexed:
            score = self._keyword_score(query_terms, entry)
            if score > 0:
                scored.append((score, entry))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        entries: list[MemoryEntry] = []
        for _, entry_data in scored[:max_results]:
            entry = self._load_by_filename(entry_data["filename"])
            if entry is not None:
                entries.append(entry)

        return entries

    def _keyword_score(
        self,
        query_terms: set[str],
        indexed_entry: dict[str, str],
    ) -> float:
        """Score how relevant an index entry is to the query terms."""
        text = (
            f"{indexed_entry['title']} {indexed_entry['description']}"
        ).lower()
        text_terms = set(re.findall(r"\w+", text))

        if not query_terms:
            return 0.0

        overlap = len(query_terms & text_terms)
        if overlap == 0:
            return 0.0

        # Base score from term overlap
        jaccard = overlap / len(query_terms | text_terms)
        return jaccard * 10.0  # Scale up for meaningful comparison

    # ---- Helpers ----

    def _load_by_filename(self, filename: str) -> MemoryEntry | None:
        """Load a memory entry by its filename."""
        filepath = self.storage_dir / filename
        if not filepath.exists():
            return None

        raw = filepath.read_text(encoding="utf-8")
        return self._parse_memory_file(raw)

    def _parse_memory_file(self, raw: str) -> MemoryEntry | None:
        """Parse a memory Markdown file into a MemoryEntry."""
        if not raw.startswith("---"):
            return None

        parts = raw.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter_raw = parts[1].strip()
        body = parts[2].strip()

        frontmatter: dict[str, str] = {}
        for line in frontmatter_raw.splitlines():
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                frontmatter[key.strip()] = value.strip()

        return MemoryEntry.from_frontmatter(frontmatter, body)

    def list_all(self) -> list[MemoryEntry]:
        """Load all memories (for admin/debug)."""
        indexed = self.index.read_index()
        entries = []
        for entry in indexed:
            mem = self._load_by_filename(entry["filename"])
            if mem is not None:
                entries.append(mem)
        return entries
