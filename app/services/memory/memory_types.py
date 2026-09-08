"""
Memory type taxonomy — adapted from Claude Code's structured memory system.

Four constrained types for information NOT derivable from current project state.
Code patterns, architecture, git history, and file structure are derivable
(via code search / git / existing docs) and should NOT be saved as memories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    """Memory types mirroring Claude Code's taxonomy."""

    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


MEMORY_TYPES = tuple(MemoryType)


@dataclass(slots=True)
class MemoryEntry:
    """A single structured memory entry stored as an independent file."""

    # Core fields
    name: str
    description: str
    type: MemoryType

    # Content
    content: str = ""

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Optional: which session created this (nullable for cross-session memories)
    source_session_id: str | None = None

    # Extra frontmatter fields
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, raw: dict[str, Any], body: str) -> MemoryEntry | None:
        """Parse a memory entry from frontmatter dict + body text."""
        name = str(raw.get("name", "")).strip()
        description = str(raw.get("description", "")).strip()
        type_raw = str(raw.get("type", "")).strip().lower()

        if not name or not description:
            return None

        try:
            mem_type = MemoryType(type_raw)
        except ValueError:
            return None

        return cls(
            name=name,
            description=description,
            type=mem_type,
            content=(body or "").strip(),
        )

    def to_frontmatter(self) -> str:
        """Serialize to the Markdown+frontmatter memory file format."""
        lines = [
            "---",
            f"name: {self.name}",
            f"description: {self.description}",
            f"type: {self.type.value}",
            "---",
            "",
            self.content,
        ]
        return "\n".join(lines)


# ---- Guidance strings for system prompt injection ----

WHEN_TO_SAVE_GUIDANCE: dict[MemoryType, str] = {
    MemoryType.USER: (
        "Save when you learn details about the user's role, preferences, "
        "responsibilities, or knowledge. Also save when you learn about "
        "their research interests, preferred analysis depth, or workflow habits."
    ),
    MemoryType.FEEDBACK: (
        "Save when the user CORRECTS your approach OR confirms a non-obvious "
        "approach worked. Record from failure AND success. Include *why* so "
        "future sessions can judge edge cases."
    ),
    MemoryType.PROJECT: (
        "Save when you learn who is doing what, why, or by when — deadlines, "
        "research goals, paper submission targets, collaboration plans. "
        "Convert relative dates to absolute dates (e.g. 'next Friday' → '2026-05-10')."
    ),
    MemoryType.REFERENCE: (
        "Save when you learn about external resources: Zotero libraries, "
        "arXiv collections, shared drives, API keys for research tools, "
        "external databases, or Slack channels for the research group."
    ),
}

HOW_TO_USE_GUIDANCE: dict[MemoryType, str] = {
    MemoryType.USER: (
        "Use when work should be informed by the user's profile or perspective. "
        "Tailor analysis depth, methodology focus, and terminology to the user."
    ),
    MemoryType.FEEDBACK: (
        "Let these guide your behavior so the user does not need to repeat "
        "the same guidance. Check feedback before starting similar tasks."
    ),
    MemoryType.PROJECT: (
        "Use to understand broader context and motivation behind the user's "
        "request. Anticipate coordination issues and deadlines."
    ),
    MemoryType.REFERENCE: (
        "Use when the user references an external system or when you need "
        "up-to-date information from outside the project directory."
    ),
}

BODY_STRUCTURE_GUIDANCE = (
    "Lead with the rule or fact, then a **Why:** line and a "
    "**How to apply:** line. Knowing *why* lets you judge edge cases "
    "instead of blindly following the rule."
)

WHAT_NOT_TO_SAVE: list[str] = [
    "Code patterns, conventions, architecture, file paths, or project structure",
    "Git history, recent changes, or who-changed-what",
    "Debugging solutions or fix recipes",
    "Anything already documented in CLAUDE.md or README files",
    "Ephemeral task details: in-progress work, temporary state, current conversation context",
    "Greetings, acknowledgments, or trivial acknowledgments ('thanks', 'ok', '收到')",
]

DRIFT_CAVEAT = (
    "Memory records can become stale over time. Before acting on a memory "
    "that names a specific file, function, or resource, verify it still "
    "exists. If a recalled memory conflicts with current observations, "
    "trust what you see now — and update or remove the stale memory."
)


def build_memory_system_prompt() -> str:
    """Build the memory section for injection into the system prompt."""
    parts = [
        "## Memory System",
        "",
        "You have access to a persistent, file-based memory system. "
        "Memories are stored as independent Markdown files with YAML "
        "frontmatter. MEMORY.md serves as the index.",
        "",
        "### Types of memory",
        "",
    ]

    for mem_type in MemoryType:
        parts.append(f"**{mem_type.value}**")
        parts.append(f"- When to save: {WHEN_TO_SAVE_GUIDANCE[mem_type]}")
        parts.append(f"- How to use: {HOW_TO_USE_GUIDANCE[mem_type]}")
        parts.append(f"- Body structure: {BODY_STRUCTURE_GUIDANCE}")
        parts.append("")

    parts.append("### What NOT to save")
    for item in WHAT_NOT_TO_SAVE:
        parts.append(f"- {item}")
    parts.append("")

    parts.append(f"### Memory drift\n{DRIFT_CAVEAT}")
    parts.append("")

    return "\n".join(parts)
