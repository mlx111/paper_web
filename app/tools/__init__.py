"""Tool package exports and lazy registry access."""

from __future__ import annotations

import importlib
from typing import Any

from .registry_factory import TOOL_EXPORTS, build_tool_registry
from .tool_registry import ToolCategory, ToolMeta, ToolRegistry
from .tool_result import ToolResult
from .tool_wrapper import ToolWrapper


class _LazyToolRegistry:
    def __init__(self):
        self._registry: ToolRegistry | None = None

    def _get_registry(self) -> ToolRegistry:
        if self._registry is None:
            self._registry = build_tool_registry()
        return self._registry

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_registry(), name)


tool_registry = _LazyToolRegistry()


def __getattr__(name: str) -> Any:
    export = TOOL_EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module 'tools' has no attribute {name!r}")
    module_name, attr_name = export
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = [
    "retrieve_knowledge",
    "get_current_time",
    "summary_message",
    "web_search",
    "academic_search_papers",
    "get_paper_abstract",
    "get_paper_bibtex",
    "search_github_repos",
    "build_citation_pool",
    "review_paper_quality",
    "extract_document_text",
    "ToolResult",
    "ToolCategory",
    "ToolMeta",
    "ToolRegistry",
    "ToolWrapper",
    "build_tool_registry",
    "tool_registry",
]
