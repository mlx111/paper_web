from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Iterable

from .tool_registry import ToolCategory, ToolMeta, ToolRegistry


@dataclass(frozen=True)
class ToolSpec:
    name: str
    module: str
    attr: str
    description: str
    category: ToolCategory
    permission: str = "allow"
    args_description: str = ""


TOOL_SPECS: dict[str, ToolSpec] = {
    "academic_search_papers": ToolSpec(
        name="academic_search_papers",
        module="tools.academic_tool",
        attr="academic_search_papers",
        description="Search academic papers by keyword query across multiple engines",
        category=ToolCategory.ACADEMIC,
        args_description="query (str), result_limit (int, default 5), min_year (int, optional)",
    ),
    "get_paper_abstract": ToolSpec(
        name="get_paper_abstract",
        module="tools.academic_tool",
        attr="get_paper_abstract",
        description="Get a detailed abstract for an academic paper by URL and title",
        category=ToolCategory.ACADEMIC,
        args_description="url (str), title (str)",
    ),
    "get_paper_bibtex": ToolSpec(
        name="get_paper_bibtex",
        module="tools.academic_tool",
        attr="get_paper_bibtex",
        description="Get BibTeX citation for an academic paper by URL and title",
        category=ToolCategory.ACADEMIC,
        args_description="url (str), title (str)",
    ),
    "search_github_repos": ToolSpec(
        name="search_github_repos",
        module="tools.academic_tool",
        attr="search_github_repos",
        description="Search GitHub repositories by keywords for open-source projects and code",
        category=ToolCategory.ACADEMIC,
        args_description="query (str), result_limit (int, default 5)",
    ),
    "review_paper_quality": ToolSpec(
        name="review_paper_quality",
        module="tools.paper_refiner_tool",
        attr="review_paper_quality",
        description="Review a paper's novelty, significance, soundness, strengths and weaknesses",
        category=ToolCategory.REFINER,
        args_description="paper_text (str), title (str, optional)",
    ),
    "build_citation_pool": ToolSpec(
        name="build_citation_pool",
        module="tools.paper_refiner_tool",
        attr="build_citation_pool",
        description="Build a citation pool by searching related papers for a topic or abstract",
        category=ToolCategory.REFINER,
        args_description="topic (str), max_papers (int, default 5), engine (str), include_bibtex (bool)",
    ),
    "retrieve_knowledge": ToolSpec(
        name="retrieve_knowledge",
        module="tools.rag_tool",
        attr="retrieve_knowledge",
        description="Retrieve document chunks from the knowledge base for answering questions",
        category=ToolCategory.KNOWLEDGE,
        args_description="query (str)",
    ),
    "web_search": ToolSpec(
        name="web_search",
        module="tools.websearch_tool",
        attr="web_search",
        description="Multi-provider web search with automatic fallback across Tavily and backups",
        category=ToolCategory.KNOWLEDGE,
        args_description="query (str), count (int, default 5)",
    ),
    "get_current_time": ToolSpec(
        name="get_current_time",
        module="tools.time_tool",
        attr="get_current_time",
        description="Get the current time in a specified timezone",
        category=ToolCategory.UTILITY,
        args_description="timezone (str, default 'Asia/Shanghai')",
    ),
    "extract_document_text": ToolSpec(
        name="extract_document_text",
        module="tools.document_parser_tool",
        attr="extract_document_text",
        description="Extract text from a local document file (PDF, DOCX, HTML, TXT, Markdown)",
        category=ToolCategory.DOCUMENT,
        args_description="file_path (str), summary_length (int, default 5000)",
    ),
}

TOOL_EXPORTS: dict[str, tuple[str, str]] = {
    name: (spec.module, spec.attr) for name, spec in TOOL_SPECS.items()
}
TOOL_EXPORTS["summary_message"] = ("tools.message_tool", "summary_message")
TOOL_EXPORTS["send_email"] = ("tools.mail_tool", "send_email")

# Tools that require human approval before execution
HITL_TOOLS: set[str] = {"send_email"}


def _load_tool_ref(spec: ToolSpec):
    module = importlib.import_module(spec.module)
    return getattr(module, spec.attr)


def build_tool_registry(tool_names: Iterable[str] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    selected_names = list(tool_names) if tool_names is not None else list(TOOL_SPECS)

    for name in selected_names:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            continue
        registry.register(ToolMeta(
            name=spec.name,
            description=spec.description,
            category=spec.category,
            permission=spec.permission,
            args_description=spec.args_description,
            tool_ref=_load_tool_ref(spec),
        ))

    return registry
