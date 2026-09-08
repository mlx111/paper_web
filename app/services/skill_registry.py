"""Skill registry — auto-load, lookup, and invoke skills."""

from __future__ import annotations

from models.skill import SkillDef
from services.skill_loader import SkillLoader


class SkillRegistry:
    """Registry that loads all skills from disk and provides lookup by name/tag/keyword."""

    def __init__(self, loader: SkillLoader | None = None):
        self.loader = loader or SkillLoader()
        self._skills: dict[str, SkillDef] = {}
        self._loaded = False

    @property
    def skills(self) -> list[SkillDef]:
        self._ensure_loaded()
        return list(self._skills.values())

    @property
    def skill_count(self) -> int:
        self._ensure_loaded()
        return len(self._skills)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        for skill in self.loader.load_all():
            self._skills[skill.name] = skill
        self._loaded = True

    def reload(self) -> None:
        self._skills.clear()
        self._loaded = False
        self._ensure_loaded()

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> SkillDef | None:
        self._ensure_loaded()
        return self._skills.get(name)

    def find_by_tag(self, tag: str) -> list[SkillDef]:
        self._ensure_loaded()
        tag_lower = tag.lower()
        return [s for s in self._skills.values() if tag_lower in (t.lower() for t in s.tags)]

    def find_by_trigger(self, text: str) -> list[SkillDef]:
        self._ensure_loaded()
        text_lower = text.lower()
        matches: list[SkillDef] = []
        for skill in self._skills.values():
            for kw in skill.trigger_keywords:
                if kw.lower() in text_lower:
                    matches.append(skill)
                    break
        return matches

    def list_names(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._skills.keys())

    def list_summaries(self) -> list[dict[str, str]]:
        self._ensure_loaded()
        return [
            {
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
                "trigger_keywords": s.trigger_keywords,
            }
            for s in sorted(self._skills.values(), key=lambda x: x.name)
        ]

    # ------------------------------------------------------------------
    # invocation helpers
    # ------------------------------------------------------------------

    def resolve_body(self, name: str, variables: dict[str, str] | None = None) -> str:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Skill not found: {name}")
        return skill.resolve_body(variables)

    def get_tools(self, name: str) -> list[str]:
        skill = self.get(name)
        if skill is None:
            return []
        return skill.enabled_tools

    def get_disabled_tools(self, name: str) -> list[str]:
        skill = self.get(name)
        if skill is None:
            return []
        return skill.disabled_tools


# module-level singleton
skill_registry = SkillRegistry()
