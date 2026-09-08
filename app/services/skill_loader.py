"""Scan and parse skill Markdown files from the skills directory."""

from __future__ import annotations

from pathlib import Path

import yaml

from models.skill import SkillDef


class SkillLoader:
    """Scan a directory for .md skill files and parse them into SkillDef objects."""

    def __init__(self, skills_dir: str | Path = ""):
        if not skills_dir:
            skills_dir = Path(__file__).resolve().parent.parent / "skills"
        self.skills_dir = Path(skills_dir)

    def load_all(self) -> list[SkillDef]:
        if not self.skills_dir.exists():
            return []

        skills: list[SkillDef] = []
        for md_path in sorted(self.skills_dir.glob("*.md")):
            try:
                skill = self._parse_file(md_path)
                if skill:
                    skills.append(skill)
            except Exception:
                pass
        return skills

    def load_one(self, name: str) -> SkillDef | None:
        path = self.skills_dir / f"{name}.md"
        if not path.exists():
            return None
        return self._parse_file(path)

    def _parse_file(self, path: Path) -> SkillDef | None:
        text = path.read_text(encoding="utf-8")
        return self._parse_skill(text, str(path))

    @staticmethod
    def _parse_skill(text: str, source: str = "") -> SkillDef | None:
        """Parse a skill markdown string into a SkillDef.

        Expected format:
        ---
        name: skill-name
        description: What this skill does
        trigger_keywords:
          - keyword1
          - keyword2
        enabled_tools:
          - tool_a
        tags:
          - analysis
        ---

        Body content with {{variable}} placeholders.
        """
        text = text.strip()
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter_str = parts[1].strip()
        body = parts[2].strip()

        try:
            meta = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict):
            return None

        name = meta.get("name", "")
        if not name:
            return None

        return SkillDef(
            name=str(name),
            description=str(meta.get("description", "")),
            version=str(meta.get("version", "1.0")),
            trigger_keywords=_as_str_list(meta.get("trigger_keywords")),
            enabled_tools=_as_str_list(meta.get("enabled_tools")),
            disabled_tools=_as_str_list(meta.get("disabled_tools")),
            tags=_as_str_list(meta.get("tags")),
            body_template=body,
            source_file=source,
        )


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []
