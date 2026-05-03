"""工具模块 — 供 Agent 调用的各种工具，附带统一注册中心。"""

# ---- 工具函数 ----
from .time_tool import get_current_time
from .message_tool import summary_message
from .websearch_tool import web_search
from .rag_tool import retrieve_knowledge
from .academic_tool import (
    academic_search_papers,
    get_paper_abstract,
    get_paper_bibtex,
    search_github_repos,
)
from .paper_refiner_tool import build_citation_pool, review_paper_quality
from .document_parser_tool import extract_document_text

# ---- 标准化基础设施 ----
from .tool_result import ToolResult
from .tool_registry import ToolCategory, ToolMeta, ToolRegistry
from .tool_wrapper import ToolWrapper

# ---- 全局工具注册中心 ----
tool_registry = ToolRegistry()

# Academic
tool_registry.register(ToolMeta(
    name="academic_search_papers",
    description="Search academic papers by keyword query across multiple engines",
    category=ToolCategory.ACADEMIC,
    permission="allow",
    args_description="query (str), result_limit (int, default 5), min_year (int, optional)",
    tool_ref=academic_search_papers,
))
tool_registry.register(ToolMeta(
    name="get_paper_abstract",
    description="Get a detailed abstract for an academic paper by URL and title",
    category=ToolCategory.ACADEMIC,
    permission="allow",
    args_description="url (str), title (str)",
    tool_ref=get_paper_abstract,
))
tool_registry.register(ToolMeta(
    name="get_paper_bibtex",
    description="Get BibTeX citation for an academic paper by URL and title",
    category=ToolCategory.ACADEMIC,
    permission="allow",
    args_description="url (str), title (str)",
    tool_ref=get_paper_bibtex,
))
tool_registry.register(ToolMeta(
    name="search_github_repos",
    description="Search GitHub repositories by keywords for open-source projects and code",
    category=ToolCategory.ACADEMIC,
    permission="allow",
    args_description="query (str), result_limit (int, default 5)",
    tool_ref=search_github_repos,
))

# Refiner
tool_registry.register(ToolMeta(
    name="review_paper_quality",
    description="Review a paper's novelty, significance, soundness, strengths and weaknesses",
    category=ToolCategory.REFINER,
    permission="allow",
    args_description="paper_text (str), title (str, optional)",
    tool_ref=review_paper_quality,
))
tool_registry.register(ToolMeta(
    name="build_citation_pool",
    description="Build a citation pool by searching related papers for a topic or abstract",
    category=ToolCategory.REFINER,
    permission="allow",
    args_description="topic (str), max_papers (int, default 5), engine (str), include_bibtex (bool)",
    tool_ref=build_citation_pool,
))

# Knowledge
tool_registry.register(ToolMeta(
    name="retrieve_knowledge",
    description="Retrieve document chunks from the knowledge base for answering questions",
    category=ToolCategory.KNOWLEDGE,
    permission="allow",
    args_description="query (str)",
    tool_ref=retrieve_knowledge,
))
tool_registry.register(ToolMeta(
    name="web_search",
    description="Multi-provider web search with automatic fallback across Tavily and backups",
    category=ToolCategory.KNOWLEDGE,
    permission="allow",
    args_description="query (str), count (int, default 5)",
    tool_ref=web_search,
))

# Utility
tool_registry.register(ToolMeta(
    name="get_current_time",
    description="Get the current time in a specified timezone",
    category=ToolCategory.UTILITY,
    permission="allow",
    args_description="timezone (str, default 'Asia/Shanghai')",
    tool_ref=get_current_time,
))

# Document
tool_registry.register(ToolMeta(
    name="extract_document_text",
    description="Extract text from a local document file (PDF, DOCX, HTML, TXT, Markdown)",
    category=ToolCategory.DOCUMENT,
    permission="allow",
    args_description="file_path (str), summary_length (int, default 5000)",
    tool_ref=extract_document_text,
))

# summary_message 是内部中间件，非标准工具，不注册

__all__ = [
    # Tool functions
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
    # Infrastructure
    "ToolResult",
    "ToolCategory",
    "ToolMeta",
    "ToolRegistry",
    "ToolWrapper",
    "tool_registry",
]
