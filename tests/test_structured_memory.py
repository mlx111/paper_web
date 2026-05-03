"""Tests for the new structured memory system."""

import tempfile
from pathlib import Path

import pytest

from app.services.memory.memory_types import MemoryType, MemoryEntry, build_memory_system_prompt
from app.services.memory.memory_index import MemoryIndex
from app.services.memory.memory_writer import MemoryWriter
from app.services.memory.memory_selector import MemorySelector


class TestMemoryTypes:
    """Test the four memory types and guidance strings."""

    def test_all_types_have_guidance(self):
        for mt in MemoryType:
            from app.services.memory.memory_types import WHEN_TO_SAVE_GUIDANCE, HOW_TO_USE_GUIDANCE
            assert WHEN_TO_SAVE_GUIDANCE[mt]
            assert HOW_TO_USE_GUIDANCE[mt]

    def test_build_system_prompt(self):
        prompt = build_memory_system_prompt()
        assert "Memory System" in prompt
        assert "user" in prompt
        assert "feedback" in prompt
        assert "project" in prompt
        assert "reference" in prompt
        assert "NOT to save" in prompt or "NOT to save" in prompt

    def test_entry_roundtrip(self):
        entry = MemoryEntry(
            name="test_memory",
            description="A test memory",
            type=MemoryType.PROJECT,
            content="This is the content.\n\n**Why:** Testing.\n**How to apply:** Just test.",
        )
        fm = entry.to_frontmatter()
        assert fm.startswith("---")
        assert "name: test_memory" in fm
        assert "type: project" in fm
        assert "This is the content" in fm

        # Parse back
        parts = fm.split("---", 2)
        frontmatter_raw = parts[1].strip()
        body = parts[2].strip()

        frontmatter = {}
        for line in frontmatter_raw.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                frontmatter[k.strip()] = v.strip()

        parsed = MemoryEntry.from_frontmatter(frontmatter, body)
        assert parsed is not None
        assert parsed.name == "test_memory"
        assert parsed.type == MemoryType.PROJECT

    def test_from_frontmatter_rejects_invalid_type(self):
        result = MemoryEntry.from_frontmatter(
            {"name": "x", "description": "y", "type": "invalid"},
            "body",
        )
        assert result is None

    def test_from_frontmatter_rejects_missing_fields(self):
        assert MemoryEntry.from_frontmatter({"name": "", "description": ""}, "body") is None
        assert MemoryEntry.from_frontmatter({"name": "x"}, "body") is None


class TestMemoryIndex:
    """Test the MEMORY.md index manager."""

    def test_add_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = MemoryIndex(Path(tmp))
            index.add_entry("test.md", "Test Memory", "A test entry")
            entries = index.read_index()
            assert len(entries) == 1
            assert entries[0]["filename"] == "test.md"
            assert entries[0]["title"] == "Test Memory"

    def test_duplicate_add_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = MemoryIndex(Path(tmp))
            index.add_entry("test.md", "First", "desc 1")
            index.add_entry("test.md", "Updated", "desc 2")
            entries = index.read_index()
            assert len(entries) == 1
            assert entries[0]["title"] == "Updated"

    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = MemoryIndex(Path(tmp))
            index.add_entry("test.md", "Test", "desc")
            assert index.remove_entry("test.md") is True
            assert index.remove_entry("test.md") is False
            assert len(index.read_index()) == 0

    def test_is_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = MemoryIndex(Path(tmp))
            assert index.is_indexed("test.md") is False
            index.add_entry("test.md", "Test", "desc")
            assert index.is_indexed("test.md") is True

    def test_empty_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = MemoryIndex(Path(tmp))
            assert index.read_index() == []


class TestMemoryWriter:
    """Test the memory writer."""

    def test_save_manual_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MemoryWriter(Path(tmp))
            entry = writer.save_manual(
                "User Prefers Deep Analysis",
                "The user prefers detailed methodology analysis.\n\n**Why:** Observed from multiple sessions.\n**How to apply:** Always include methodology breakdown.",
                MemoryType.USER,
            )
            assert entry is not None
            assert entry.name == "User Prefers Deep Analysis"

            # Check file exists
            files = list(Path(tmp).glob("*.md"))
            assert len(files) >= 1  # MEMORY.md + memory file

            # Check index
            entries = writer.index.read_index()
            assert len(entries) == 1

    def test_rejects_low_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MemoryWriter(Path(tmp))
            entry = writer.evaluate_and_save(
                "thanks",
                "you're welcome, have a nice day!",
            )
            assert entry is None
            # No files created except possibly MEMORY.md
            md_files = [f for f in Path(tmp).glob("*.md") if f.name != "MEMORY.md"]
            assert len(md_files) == 0

    def test_dedup_prevents_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MemoryWriter(Path(tmp))
            entry1 = writer.save_manual("Test Title", "Test content for dedup.", MemoryType.PROJECT)
            entry2 = writer.save_manual("Test Title", "Test content for dedup.", MemoryType.PROJECT)
            assert entry1 is not None
            # Dedup updates existing entry and returns it — no duplicate file created
            assert entry2 is not None
            assert entry2.name == entry1.name
            # Only one memory file (plus MEMORY.md)
            md_files = [f for f in Path(tmp).glob("*.md") if f.name != "MEMORY.md"]
            assert len(md_files) == 1

    def test_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MemoryWriter(Path(tmp))
            writer.save_manual("To Delete", "Some memory content to clean up later.", MemoryType.REFERENCE)
            assert writer.delete_memory("To Delete") is True
            assert writer.delete_memory("To Delete") is False


class TestMemorySelector:
    """Test the memory selector."""

    def test_select_keyword_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MemoryWriter(Path(tmp))
            writer.save_manual(
                "User NLP Research Interest",
                "User focuses on NLP research, especially attention mechanisms.",
                MemoryType.USER,
            )
            writer.save_manual(
                "Submission Deadline June 2026",
                "Paper submission deadline for ACL is June 15, 2026.",
                MemoryType.PROJECT,
            )
            writer.save_manual(
                "Zotero Library Path",
                "The shared Zotero library is at /data/zotero/library.",
                MemoryType.REFERENCE,
            )

            selector = MemorySelector(Path(tmp))
            results = selector.select_sync("attention mechanism in transformers", max_results=3)
            assert len(results) >= 1
            # Should find the NLP interest memory
            names = [r.name for r in results]
            assert any("NLP" in n for n in names) or any("Research" in n for n in names)

    def test_select_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MemoryWriter(Path(tmp))
            writer.save_manual("Test", "Irrelevant content about cooking.", MemoryType.USER)
            selector = MemorySelector(Path(tmp))
            results = selector.select_sync("quantum physics", max_results=5)
            # May or may not match — keyword fallback is weak by design
            # Nothing specific to assert, just ensure it doesn't crash
            assert isinstance(results, list)
