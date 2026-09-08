"""Skill definition model — Markdown + YAML frontmatter skill schema."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillDef:
    """A skill parsed from a Markdown file with YAML frontmatter.

    Skills are reusable prompt templates with metadata. The body_template
    supports {{variable}} placeholders filled at invocation time.
    """

    name: str
    description: str = ""
    version: str = "1.0"
    trigger_keywords: list[str] = field(default_factory=list)
    enabled_tools: list[str] = field(default_factory=list)
    disabled_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    body_template: str = ""
    source_file: str = ""

    def resolve_body(self, variables: dict[str, str] | None = None) -> str:
        """Fill {{variable}} placeholders in the body template."""
        import re

        body = self.body_template
        if variables:
            for key, value in variables.items():
                body = body.replace("{{" + key + "}}", str(value))
        return body
