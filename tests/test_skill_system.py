"""Tests for skill loader, registry, and SkillDef model."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.skill import SkillDef
from app.services.skill_loader import SkillLoader
from app.services.skill_registry import SkillRegistry


# ---------------------------------------------------------------------------
# TestSkillDef
# ---------------------------------------------------------------------------

class TestSkillDef:
    def test_resolve_body_substitutes_variables(self):
        skill = SkillDef(
            name="test",
            body_template="Hello {{name}}, your topic is {{topic}}.",
        )
        result = skill.resolve_body({"name": "Alice", "topic": "AI"})
        assert result == "Hello Alice, your topic is AI."

    def test_resolve_body_without_variables_returns_unchanged(self):
        skill = SkillDef(
            name="test",
            body_template="No placeholders here.",
        )
        result = skill.resolve_body()
        assert result == "No placeholders here."


# ---------------------------------------------------------------------------
# TestSkillLoader
# ---------------------------------------------------------------------------

SAMPLE_SKILL = """---
name: test-skill
description: A sample skill for testing
trigger_keywords:
  - test
  - sample
enabled_tools:
  - tool_a
  - tool_b
tags:
  - testing
  - demo
---
# Test Skill

This is the body with {{variable}} placeholders.
"""

NO_FRONTMATTER = """# No Frontmatter

This file has no YAML frontmatter.
"""

NO_NAME = """---
description: Missing the name field
---
Body content.
"""

MINIMAL_SKILL = """---
name: minimal
---
Just a body, no metadata.
"""


class TestSkillLoader:
    def test_parse_valid_skill(self):
        skill = SkillLoader._parse_skill(SAMPLE_SKILL, "test-skill.md")
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A sample skill for testing"
        assert skill.trigger_keywords == ["test", "sample"]
        assert skill.enabled_tools == ["tool_a", "tool_b"]
        assert skill.tags == ["testing", "demo"]
        assert "{{variable}}" in skill.body_template
        assert skill.source_file == "test-skill.md"

    def test_parse_no_frontmatter_returns_none(self):
        skill = SkillLoader._parse_skill(NO_FRONTMATTER)
        assert skill is None

    def test_parse_no_name_returns_none(self):
        skill = SkillLoader._parse_skill(NO_NAME)
        assert skill is None

    def test_parse_minimal_skill(self):
        skill = SkillLoader._parse_skill(MINIMAL_SKILL)
        assert skill is not None
        assert skill.name == "minimal"
        assert skill.description == ""
        assert skill.trigger_keywords == []
        assert skill.tags == []

    def test_load_all_from_dir(self, tmp_path):
        (tmp_path / "skill_a.md").write_text(
            "---\nname: a\ndescription: First skill\n---\nBody A",
            encoding="utf-8",
        )
        (tmp_path / "skill_b.md").write_text(
            "---\nname: b\ndescription: Second skill\ntrigger_keywords:\n  - hello\n---\nBody B",
            encoding="utf-8",
        )
        (tmp_path / "not-a-skill.txt").write_text("plain text")
        (tmp_path / "bad.md").write_text("no frontmatter")

        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()
        names = {s.name for s in skills}
        assert names == {"a", "b"}

    def test_load_all_empty_dir(self, tmp_path):
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()
        assert skills == []

    def test_load_all_dir_not_exists(self):
        loader = SkillLoader(skills_dir="/nonexistent/path")
        skills = loader.load_all()
        assert skills == []

    def test_load_one_found(self, tmp_path):
        (tmp_path / "my-skill.md").write_text(SAMPLE_SKILL, encoding="utf-8")
        loader = SkillLoader(skills_dir=tmp_path)
        skill = loader.load_one("my-skill")
        assert skill is not None
        assert skill.name == "test-skill"

    def test_load_one_not_found(self, tmp_path):
        loader = SkillLoader(skills_dir=tmp_path)
        skill = loader.load_one("nonexistent")
        assert skill is None

    def test_yaml_parse_error_returns_none(self, tmp_path):
        (tmp_path / "bad-yaml.md").write_text(
            "---\nname: [invalid: yaml: here\n---\nBody",
            encoding="utf-8",
        )
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()
        assert skills == []


# ---------------------------------------------------------------------------
# TestSkillRegistry
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    @staticmethod
    def _make_registry(skills_dir) -> SkillRegistry:
        loader = SkillLoader(skills_dir=skills_dir)
        return SkillRegistry(loader=loader)

    def test_loads_all_skills(self, tmp_path):
        (tmp_path / "a.md").write_text("---\nname: a\n---\nA", encoding="utf-8")
        (tmp_path / "b.md").write_text("---\nname: b\n---\nB", encoding="utf-8")
        reg = self._make_registry(tmp_path)
        assert reg.skill_count == 2

    def test_get_by_name(self, tmp_path):
        (tmp_path / "my.md").write_text("---\nname: my\n---\nBody", encoding="utf-8")
        reg = self._make_registry(tmp_path)
        skill = reg.get("my")
        assert skill is not None
        assert skill.name == "my"

    def test_get_missing(self, tmp_path):
        reg = self._make_registry(tmp_path)
        assert reg.get("nope") is None

    def test_find_by_tag(self, tmp_path):
        (tmp_path / "a.md").write_text(
            "---\nname: a\ntags:\n  - ml\n  - nlp\n---\nA", encoding="utf-8"
        )
        (tmp_path / "b.md").write_text(
            "---\nname: b\ntags:\n  - systems\n---\nB", encoding="utf-8"
        )
        reg = self._make_registry(tmp_path)
        assert len(reg.find_by_tag("ml")) == 1
        assert reg.find_by_tag("ml")[0].name == "a"
        assert len(reg.find_by_tag("systems")) == 1
        assert len(reg.find_by_tag("nonexistent")) == 0

    def test_find_by_trigger(self, tmp_path):
        (tmp_path / "a.md").write_text(
            "---\nname: a\ntrigger_keywords:\n  - analyze\n  - deep dive\n---\nA",
            encoding="utf-8",
        )
        (tmp_path / "b.md").write_text(
            "---\nname: b\ntrigger_keywords:\n  - format\n---\nB",
            encoding="utf-8",
        )
        reg = self._make_registry(tmp_path)
        matches = reg.find_by_trigger("please analyze this paper")
        assert len(matches) == 1
        assert matches[0].name == "a"
        assert len(reg.find_by_trigger("no match here")) == 0

    def test_list_names(self, tmp_path):
        (tmp_path / "a.md").write_text("---\nname: a\n---\nA", encoding="utf-8")
        (tmp_path / "b.md").write_text("---\nname: b\n---\nB", encoding="utf-8")
        reg = self._make_registry(tmp_path)
        assert reg.list_names() == ["a", "b"]

    def test_list_summaries(self, tmp_path):
        (tmp_path / "a.md").write_text(
            "---\nname: a\ndescription: desc a\ntags:\n  - t1\n---\nA",
            encoding="utf-8",
        )
        reg = self._make_registry(tmp_path)
        summaries = reg.list_summaries()
        assert len(summaries) == 1
        assert summaries[0]["name"] == "a"
        assert summaries[0]["description"] == "desc a"

    def test_resolve_body(self, tmp_path):
        (tmp_path / "greet.md").write_text(
            "---\nname: greet\n---\nHi {{user}}!",
            encoding="utf-8",
        )
        reg = self._make_registry(tmp_path)
        result = reg.resolve_body("greet", {"user": "Bob"})
        assert result == "Hi Bob!"

    def test_resolve_body_missing_skill_raises(self, tmp_path):
        reg = self._make_registry(tmp_path)
        with pytest.raises(KeyError):
            reg.resolve_body("nope", {})

    def test_get_tools(self, tmp_path):
        (tmp_path / "tooled.md").write_text(
            "---\nname: tooled\nenabled_tools:\n  - search\n  - fetch\n---\nBody",
            encoding="utf-8",
        )
        reg = self._make_registry(tmp_path)
        assert reg.get_tools("tooled") == ["search", "fetch"]
        assert reg.get_tools("nope") == []

    def test_get_disabled_tools(self, tmp_path):
        (tmp_path / "no-tools.md").write_text(
            "---\nname: no-tools\ndisabled_tools:\n  - \"*\"\n---\nBody",
            encoding="utf-8",
        )
        reg = self._make_registry(tmp_path)
        assert reg.get_disabled_tools("no-tools") == ["*"]

    def test_reload_picks_up_new_files(self, tmp_path):
        (tmp_path / "a.md").write_text("---\nname: a\n---\nA", encoding="utf-8")
        reg = self._make_registry(tmp_path)
        assert reg.skill_count == 1
        (tmp_path / "b.md").write_text("---\nname: b\n---\nB", encoding="utf-8")
        reg.reload()
        assert reg.skill_count == 2

    def test_reload_removes_deleted_files(self, tmp_path):
        a_file = tmp_path / "a.md"
        a_file.write_text("---\nname: a\n---\nA", encoding="utf-8")
        reg = self._make_registry(tmp_path)
        assert reg.skill_count == 1
        a_file.unlink()
        reg.reload()
        assert reg.skill_count == 0


# ---------------------------------------------------------------------------
# TestRealSkills
# ---------------------------------------------------------------------------

class TestRealSkills:
    """Verify the bundled skill .md files can be parsed."""

    def test_all_bundled_skills_load(self):
        loader = SkillLoader()
        skills = loader.load_all()
        assert len(skills) >= 3
        names = {s.name for s in skills}
        assert "paper-analyzer" in names
        assert "citation-formatter" in names
        assert "research-question-generator" in names

    def test_bundled_skills_have_required_fields(self):
        loader = SkillLoader()
        for skill in loader.load_all():
            assert skill.name, f"Skill {skill.source_file} missing name"
            assert skill.description, f"Skill {skill.name} missing description"
            assert skill.body_template, f"Skill {skill.name} missing body"


# ---------------------------------------------------------------------------
# TestSkillRegistrySingleton
# ---------------------------------------------------------------------------

class TestSkillRegistrySingleton:
    def test_singleton_exists_and_loads(self):
        from app.services.skill_registry import skill_registry
        assert skill_registry.skill_count >= 3
