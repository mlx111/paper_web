"""
MEMORY.md index file management.

MEMORY.md is the index — not a memory itself. Each line is one entry
under ~150 characters: `- [Title](file.md) — one-line hook`.

Constraints:
- Max 200 lines (after that, older entries are truncated)
- Max 25,000 bytes
- One entry per memory file, sorted alphabetically
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000
INDEX_FILENAME = "MEMORY.md"

# Pattern: - [Name](path.md) — description
ENTRY_PATTERN = re.compile(r"^-\s*\[([^\]]+)\]\(([^)]+\.md)\)\s*[—\-]\s*(.+)$")


class MemoryIndex:
    """Manages the MEMORY.md index file."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.storage_dir / INDEX_FILENAME

    # ---- Read ----

    def read_index(self) -> list[dict[str, str]]:
        """Parse MEMORY.md into a list of {filename, title, description} entries."""
        if not self.index_path.exists():
            return []

        raw = self.index_path.read_text(encoding="utf-8")
        entries: list[dict[str, str]] = []

        for line in raw.splitlines():
            line = line.strip()
            if not line or not line.startswith("- ["):
                continue
            m = ENTRY_PATTERN.match(line)
            if m:
                entries.append({
                    "title": m.group(1).strip(),
                    "filename": m.group(2).strip(),
                    "description": m.group(3).strip(),
                })

        return entries

    def is_indexed(self, filename: str) -> bool:
        """Check if a filename already has an index entry."""
        entries = self.read_index()
        target = str(Path(filename).name)
        return any(e["filename"] == target for e in entries)

    # ---- Write ----

    def add_entry(self, filename: str, title: str, description: str) -> None:
        """Add or update an entry in the index."""
        entries = self.read_index()
        fname = Path(filename).name

        # Remove existing entry for this file if present
        entries = [e for e in entries if e["filename"] != fname]

        # Add new entry at the top (most recent first)
        desc = (description or "").strip()
        if len(desc) > 100:
            desc = desc[:97] + "..."

        entries.insert(0, {
            "title": (title or "").strip(),
            "filename": fname,
            "description": desc,
        })

        self._write(entries)

    def remove_entry(self, filename: str) -> bool:
        """Remove an entry from the index. Returns True if found and removed."""
        entries = self.read_index()
        fname = Path(filename).name
        new_entries = [e for e in entries if e["filename"] != fname]

        if len(new_entries) == len(entries):
            return False

        self._write(new_entries)
        return True

    def update_entry_description(self, filename: str, new_description: str) -> bool:
        """Update just the description of an existing entry."""
        entries = self.read_index()
        fname = Path(filename).name

        for e in entries:
            if e["filename"] == fname:
                desc = (new_description or "").strip()
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                e["description"] = desc
                self._write(entries)
                return True

        return False

    # ---- Internal ----

    def _write(self, entries: list[dict[str, str]]) -> None:
        """Write the index, applying line and byte caps."""
        # Sort: most recent first (already inserted at top above)
        lines: list[str] = [
            "# Memory Index",
            "",
            "This file is the index of all memories. Each line points to a memory file.",
            f"Auto-generated. Do not edit manually. Max {MAX_INDEX_LINES} entries.",
            "",
        ]

        for e in entries[:MAX_INDEX_LINES]:
            line = f"- [{e['title']}]({e['filename']}) — {e['description']}"
            lines.append(line)

        content = "\n".join(lines)

        # Byte cap
        if len(content.encode("utf-8")) > MAX_INDEX_BYTES:
            # Truncate entries until under the cap
            header = "\n".join(lines[:5]) + "\n"
            header_bytes = len(header.encode("utf-8"))
            remaining = MAX_INDEX_BYTES - header_bytes

            truncated_entries: list[str] = []
            for line in lines[5:]:
                line_bytes = len((line + "\n").encode("utf-8"))
                if remaining - line_bytes < 0:
                    break
                truncated_entries.append(line)
                remaining -= line_bytes

            content = header + "\n".join(truncated_entries)

            if len(entries) > len(truncated_entries):
                content += (
                    f"\n\n[Index truncated: {len(entries) - len(truncated_entries)} "
                    "entries omitted due to size limit]"
                )

        # Atomic write
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self.index_path)

    def clear(self) -> None:
        """Remove the index file entirely."""
        if self.index_path.exists():
            self.index_path.unlink()
