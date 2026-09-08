"""
Centralized tool registry with metadata and permission model.

Provides:
- Tool registration with category/permission metadata
- Lookup by name or category
- Formatted description generation for prompts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from langchain_core.tools import BaseTool


class ToolCategory(Enum):
    ACADEMIC = "academic"
    KNOWLEDGE = "knowledge"
    UTILITY = "utility"
    DOCUMENT = "document"
    REFINER = "refiner"


@dataclass
class ToolMeta:
    """Metadata for a registered tool."""

    name: str
    description: str
    category: ToolCategory
    permission: str = "allow"  # allow / ask_user / deny
    is_concurrency_safe: bool = True
    args_description: str = ""
    tool_ref: BaseTool | None = None

    def format_for_prompt(self) -> str:
        """Single-line description for agent prompts."""
        base = f"- {self.name}: {self.description}"
        if self.args_description:
            base += f"\n  Arguments: {self.args_description}"
        return base


class ToolRegistry:
    """Central registry for all tools in the system."""

    def __init__(self):
        self._tools: dict[str, ToolMeta] = {}

    def register(self, meta: ToolMeta) -> None:
        """Register a tool. Overwrites if name already exists."""
        self._tools[meta.name] = meta

    def get(self, name: str) -> ToolMeta | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> list[ToolMeta]:
        """Return all registered tools."""
        return list(self._tools.values())

    def list_by_category(self, category: ToolCategory) -> list[ToolMeta]:
        """Return tools filtered by category."""
        return [m for m in self._tools.values() if m.category == category]

    def list_by_permission(self, permission: str) -> list[ToolMeta]:
        """Return tools with a specific permission level."""
        return [m for m in self._tools.values() if m.permission == permission]

    def get_tools_list(self, names: list[str] | None = None) -> list[BaseTool]:
        """
        Return LangChain tool objects for binding to models.

        If names is provided, only return those tools. Otherwise return all.
        """
        result: list[BaseTool] = []
        for name, meta in self._tools.items():
            if names and name not in names:
                continue
            if meta.tool_ref is not None:
                result.append(meta.tool_ref)
        return result

    def format_descriptions(self, category: ToolCategory | None = None) -> str:
        """Generate a formatted tool description block for system prompts."""
        tools = self.list_by_category(category) if category else self.list_all()
        if not tools:
            return "(no tools available)"
        return "\n".join(t.format_for_prompt() for t in tools)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
