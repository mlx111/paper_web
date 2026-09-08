"""
MemoryWriter — decides what to save, infers types, handles dedup.

Mirrors Claude Code's auto-memory behavior: after each turn, evaluate
whether the exchange contains information worth persisting.
"""

from __future__ import annotations

import re
from datetime import datetime
from hashlib import md5
from pathlib import Path

from .memory_index import MemoryIndex
from .memory_types import MemoryEntry, MemoryType, WHAT_NOT_TO_SAVE


# Patterns indicating low-value content that should NOT be saved
LOW_VALUE_PATTERNS: tuple[str, ...] = (
    "thanks", "thank you", "ok", "okay", "hello", "hi",
    "收到", "谢谢", "好的", "知道了", "明白了", "随便", "无所谓",
    "再见", "拜拜", "晚安", "早安",
)

# Signals suggesting this IS worth saving
HIGH_VALUE_SIGNALS: tuple[str, ...] = (
    "important", "must", "should", "remember", "constraint",
    "decision", "prefer", "always", "never", "key",
    "important for later", "deadline", "submission",
    "重要", "必须", "约束", "决定", "偏好", "记住", "以后", "不要",
    "截止", "提交", "目标",
)

# Keyword → MemoryType hints for auto-classification
TYPE_HINTS: list[tuple[tuple[str, ...], MemoryType]] = [
    # FEEDBACK first — corrective intent takes priority over user
    # profiling when both could match (e.g. "不是这个意思我是想让你..."
    # contains "我是" but is clearly corrective).
    (
        ("don't", "stop doing", "never do", "please don't",
         "shouldn't", "instead of", "not that",
         "不要", "别", "不应该", "不是这样", "改一下",
         "不是这个意思", "太长了", "简洁", "不对", "说错了",
         "理解错了", "你误会了"),
        MemoryType.FEEDBACK,
    ),
    (
        ("I prefer", "I like", "I usually", "my workflow", "I'm a",
         "我偏好", "我习惯", "我是", "我的研究方向", "我关注"),
        MemoryType.USER,
    ),
    (
        ("deadline", "milestone", "target", "plan to",
         "scheduled", "next week", "by Friday",
         "截止", "目标", "计划", "下个月", "下周", "提交"),
        MemoryType.PROJECT,
    ),
    (
        ("check the", "look at", "see the", "the file at",
         "external", "link", "url", "slack", "drive",
         "看一下", "参考", "链接", "文件在"),
        MemoryType.REFERENCE,
    ),
]

# Known low-value "kinds" from the old system that should not be auto-saved
SKIP_KINDS: frozenset[str] = frozenset({
    "note", "chat", "question", "answer",
})


class MemoryWriter:
    """Handles the write side of the memory system."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index = MemoryIndex(storage_dir)

    # ---- Public API ----

    def evaluate_and_save(
        self,
        user_message: str,
        assistant_response: str,
        *,
        session_id: str = "",
        extra_context: dict | None = None,
    ) -> MemoryEntry | None:
        """
        After each turn, evaluate whether this exchange should be saved as memory.

        Returns the saved MemoryEntry, or None if nothing was saved.
        """
        # Gate 1: Skip low-value exchanges — only check user message,
        # not assistant response (which may contain polite acknowledgments
        # like "好的" / "明白了" that would cause false rejections).
        if self._is_low_value(user_message):
            return None

        # Gate 2: Skip derivable information
        combined = f"{user_message}\n{assistant_response}"
        if self._is_derivable(combined):
            return None

        # Gate 3: Infer type
        mem_type = self._infer_type(user_message, assistant_response)

        # Gate 4: Build entry
        title = self._generate_title(user_message, mem_type)
        description = self._generate_description(user_message, mem_type)
        content = self._build_content(user_message, assistant_response, mem_type)

        if not title or not content:
            return None

        # Gate 5: Dedup check
        if self._is_duplicate(title, content):
            return None

        # Write memory file
        entry = MemoryEntry(
            name=title,
            description=description,
            type=mem_type,
            content=content,
            source_session_id=session_id or None,
        )

        self._write_memory_file(entry)
        self.index.add_entry(entry.name + ".md", entry.name, description)

        return entry

    def save_manual(
        self,
        title: str,
        content: str,
        mem_type: MemoryType = MemoryType.PROJECT,
        *,
        session_id: str = "",
    ) -> MemoryEntry | None:
        """Manually save a memory entry (e.g. called by tools or API)."""
        title = (title or "").strip()
        content = (content or "").strip()
        if not title or not content:
            return None

        if self._is_low_value(f"{title} {content}"):
            return None

        if self._is_duplicate(title, content):
            # Update the existing entry's content instead
            existing = self._find_by_title(title)
            if existing:
                existing.content = content
                existing.updated_at = datetime.now().isoformat()
                self._write_memory_file(existing)
                return existing
            return None

        # Derive description from content (first sentence or first 100 chars)
        desc = content.split("。")[0].split(".")[0].strip()
        if not desc:
            desc = content.strip()[:100]

        entry = MemoryEntry(
            name=title,
            description=desc,
            type=mem_type,
            content=content,
            source_session_id=session_id or None,
        )

        self._write_memory_file(entry)
        # Use the actual slugified filename for index consistency
        slug = self._memory_path(entry.name).name
        self.index.add_entry(slug, entry.name, desc)
        return entry

    def delete_memory(self, title: str) -> bool:
        """Delete a memory by title."""
        filepath = self._memory_path(title)
        if filepath.exists():
            filepath.unlink()
        return self.index.remove_entry(filepath.name)

    # ---- File I/O ----

    def _memory_path(self, name: str) -> Path:
        safe = re.sub(r"[^\w\-]", "_", name.lower()).strip("_")
        return self.storage_dir / f"{safe or 'memory'}.md"

    def _write_memory_file(self, entry: MemoryEntry) -> None:
        filepath = self._memory_path(entry.name)
        tmp = filepath.with_suffix(".tmp")
        tmp.write_text(entry.to_frontmatter(), encoding="utf-8")
        tmp.replace(filepath)

    def load_memory(self, filename: str) -> MemoryEntry | None:
        """Load a single memory file by filename."""
        filepath = self.storage_dir / filename
        if not filepath.exists():
            return None

        raw = filepath.read_text(encoding="utf-8")
        return self._parse_memory_file(raw)

    # ---- Parsing ----

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

    # ---- Gates ----

    def _is_low_value(self, text: str) -> bool:
        """Check if the text is just noise."""
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        # Very short content is noise
        if len(normalized) < 10:
            return True
        # Greetings / filler — use word-boundary regex to avoid false
        # positives like "hi" matching inside "his" or "this".
        for pattern in LOW_VALUE_PATTERNS:
            if re.search(rf"\b{re.escape(pattern)}\b", normalized):
                return True
        return False

    def _is_derivable(self, text: str) -> bool:
        """Check if the info is derivable from code/docs and should not be saved."""
        normalized = text.lower()
        derivable_markers = [
            "file path", "file structure", "code pattern",
            "git commit", "git log", "pull request",
            "the function", "the class", "the module",
        ]
        return any(m in normalized for m in derivable_markers)

    def _infer_type(self, user_msg: str, assistant_msg: str) -> MemoryType:
        """Heuristically infer the memory type from message content."""
        combined = f"{user_msg} {assistant_msg}".lower()

        for keywords, mem_type in TYPE_HINTS:
            for kw in keywords:
                if kw.lower() in combined:
                    return mem_type

        return MemoryType.PROJECT

    def _generate_title(self, user_msg: str, mem_type: MemoryType) -> str:
        """Generate a concise title from the user message."""
        clean = re.sub(r"\s+", " ", (user_msg or "").strip())
        # Truncate to reasonable title length
        if len(clean) > 60:
            clean = clean[:57] + "..."
        return clean

    def _generate_description(self, user_msg: str, mem_type: MemoryType) -> str:
        """Generate a one-line description for the index."""
        clean = re.sub(r"\s+", " ", (user_msg or "").strip())
        if len(clean) > 100:
            clean = clean[:97] + "..."
        return f"[{mem_type.value}] {clean}"

    def _build_content(
        self,
        user_msg: str,
        assistant_msg: str,
        mem_type: MemoryType,
    ) -> str:
        """Build the memory body content."""
        now = datetime.now().strftime("%Y-%m-%d")

        lines = [
            (user_msg or "").strip(),
            "",
            "**Why:** Extracted from conversation on " + now,
        ]

        if mem_type == MemoryType.FEEDBACK:
            lines.append("**How to apply:** Check this before similar tasks.")
        elif mem_type == MemoryType.PROJECT:
            lines.append("**How to apply:** Consider this when planning related work.")
        elif mem_type == MemoryType.USER:
            lines.append("**How to apply:** Tailor responses accordingly.")
        elif mem_type == MemoryType.REFERENCE:
            lines.append("**How to apply:** Consult when the referenced resource is needed.")

        return "\n".join(lines)

    def _is_duplicate(self, title: str, content: str) -> bool:
        """Check if a memory with near-identical content already exists."""
        title_norm = re.sub(r"\s+", " ", title.strip().lower())
        content_norm = re.sub(r"\s+", " ", content.strip().lower())
        combined_hash = md5(f"{title_norm}|{content_norm}".encode()).hexdigest()[:12]

        for entry in self.index.read_index():
            existing = self.load_memory(entry["filename"])
            if existing is None:
                continue

            existing_title = re.sub(r"\s+", " ", existing.name.strip().lower())
            existing_content = re.sub(r"\s+", " ", existing.content.strip().lower())
            existing_hash = md5(
                f"{existing_title}|{existing_content}".encode()
            ).hexdigest()[:12]

            if combined_hash == existing_hash:
                return True

            # Fuzzy: same title and content > 80% similar
            if title_norm == existing_title:
                if self._text_similarity(content_norm, existing_content) > 0.8:
                    return True

        return False

    def _find_by_title(self, title: str) -> MemoryEntry | None:
        """Find an existing memory by title match."""
        title_norm = re.sub(r"\s+", " ", title.strip().lower())
        for entry in self.index.read_index():
            existing = self.load_memory(entry["filename"])
            if existing is None:
                continue
            existing_title = re.sub(r"\s+", " ", existing.name.strip().lower())
            if title_norm == existing_title:
                return existing
        return None

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Simple character-level Jaccard similarity."""
        if not a or not b:
            return 0.0
        set_a = set(a)
        set_b = set(b)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0
