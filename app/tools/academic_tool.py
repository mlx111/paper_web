"""Academic research tools for agents."""

from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

from services.academic_tools_service import academic_tools_service


def _dump(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def _shorten(text: str, limit: int = 280) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _compact_search_payload(result: dict) -> dict:
    papers = result.get("papers") or []
    compact_papers: list[dict] = []
    for paper in papers[:3]:
        compact_papers.append(
            {
                "title": paper.get("title", ""),
                "authors": paper.get("authors", ""),
                "venue": paper.get("venue", ""),
                "year": paper.get("year", ""),
                "citation_count": paper.get("citation_count", 0),
                "url": paper.get("url", ""),
                "abstract": _shorten(paper.get("abstract", ""), limit=280),
            }
        )

    summary_lines: list[str] = []
    for index, paper in enumerate(compact_papers, 1):
        line = f"{index}. {paper['title']} ({paper['year']})"
        if paper.get("authors"):
            line += f" - {paper['authors']}"
        if paper.get("abstract"):
            line += f"\n   摘要: {paper['abstract']}"
        if paper.get("url"):
            line += f"\n   链接: {paper['url']}"
        summary_lines.append(line)

    return {
        "ok": result.get("ok", True),
        "query": result.get("query", ""),
        "engine": result.get("engine", ""),
        "num_results": int(result.get("num_results", len(compact_papers) or 0)),
        "papers": compact_papers,
        "summary": "\n\n".join(summary_lines),
        "notes": "Tool output compacted for agent context. Showing top 3 papers with shortened abstracts.",
    }


@tool(
    name_or_callable="academic_search_papers",
    description=(
        "Search academic papers by query. Use this for literature search, related work, "
        "paper recommendations, or evidence collection. Args: query, result_limit, engine "
        "(openalex, semanticscholar, arxiv)."
    ),
)
def academic_search_papers(
    query: str,
    result_limit: int = 5,
    engine: str = "openalex",
    min_year: int | None = None,
    max_papers: int | None = None,
) -> str:
    try:
        effective_limit = max_papers if max_papers is not None else result_limit
        capped_limit = max(1, min(int(effective_limit or 5), 10))
        result = academic_tools_service.search_papers(
            query=query,
            result_limit=capped_limit,
            engine=engine,
            min_year=min_year,
        )
        return _dump(_compact_search_payload(result))
    except Exception as exc:
        logger.error("academic_search_papers failed: {}", exc)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": str(exc)})


@tool(
    name_or_callable="get_paper_bibtex",
    description=(
        "Get BibTeX for an academic paper from its URL and title. "
        "Use this when the answer needs citations or references."
    ),
)
def get_paper_bibtex(url: str, title: str) -> str:
    try:
        return _dump(academic_tools_service.get_bibtex_from_url(url=url, title=title))
    except Exception as exc:
        logger.error("get_paper_bibtex failed: {}", exc)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": str(exc)})


@tool(
    name_or_callable="get_paper_abstract",
    description=(
        "Get an abstract for an academic paper from its URL and title. "
        "Use this when search results do not include enough abstract detail."
    ),
)
def get_paper_abstract(url: str, title: str) -> str:
    try:
        return _dump(academic_tools_service.get_abstract_from_url(url=url, title=title))
    except Exception as exc:
        logger.error("get_paper_abstract failed: {}", exc)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": str(exc)})
