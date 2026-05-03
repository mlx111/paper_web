"""Academic research tools for agents."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from langchain_core.tools import tool
from loguru import logger

from services.academic_tools_service import academic_tools_service
from .tool_result import ToolResult


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
        "sources_used": result.get("sources_used", []),
        "num_results": int(result.get("num_results", len(compact_papers) or 0)),
        "papers": compact_papers,
        "summary": "\n\n".join(summary_lines),
        "notes": "Tool output compacted for agent context. Showing top 3 papers with shortened abstracts.",
    }


@tool(
    name_or_callable="academic_search_papers",
    description=(
        "Search academic papers by query. Use this for literature search, related work, "
        "paper recommendations, or evidence collection. Auto-fallback across OpenAlex, "
        "CORE, Semantic Scholar, arXiv. Args: query, result_limit."
    ),
)
def academic_search_papers(
    query: str,
    result_limit: int = 5,
    min_year: int | None = None,
    max_papers: int | None = None,
) -> str:
    try:
        effective_limit = max_papers if max_papers is not None else result_limit
        capped_limit = max(1, min(int(effective_limit or 5), 10))
        result = academic_tools_service.search_papers(
            query=query,
            result_limit=capped_limit,
            engine="auto",
            min_year=min_year,
        )
        payload = _compact_search_payload(result)
        return ToolResult.success(data=payload).to_message_content()
    except Exception as exc:
        logger.error("academic_search_papers failed: {}", exc)
        return ToolResult.failure(str(exc), "TOOL_FAILED").to_message_content()


@tool(
    name_or_callable="get_paper_bibtex",
    description=(
        "Get BibTeX for an academic paper from its URL and title. "
        "Use this when the answer needs citations or references."
    ),
)
def get_paper_bibtex(url: str, title: str) -> str:
    try:
        data = academic_tools_service.get_bibtex_from_url(url=url, title=title)
        return ToolResult.success(data=data).to_message_content()
    except Exception as exc:
        logger.error("get_paper_bibtex failed: {}", exc)
        return ToolResult.failure(str(exc), "TOOL_FAILED").to_message_content()


@tool(
    name_or_callable="get_paper_abstract",
    description=(
        "Get an abstract for an academic paper from its URL and title. "
        "Use this when search results do not include enough abstract detail."
    ),
)
def get_paper_abstract(url: str, title: str) -> str:
    try:
        data = academic_tools_service.get_abstract_from_url(url=url, title=title)
        return ToolResult.success(data=data).to_message_content()
    except Exception as exc:
        logger.error("get_paper_abstract failed: {}", exc)
        return ToolResult.failure(str(exc), "TOOL_FAILED").to_message_content()


@tool(
    name_or_callable="search_github_repos",
    description=(
        "Search GitHub repositories by keywords. Use this to find open-source projects, "
        "code implementations, tools, and frameworks related to a topic. "
        "Args: query, result_limit. Returns repo name, description, stars, URL, language."
    ),
)
def search_github_repos(query: str, result_limit: int = 5) -> str:
    try:
        capped_limit = max(1, min(int(result_limit or 5), 10))
        github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_KEY") or ""
        url = f"https://api.github.com/search/repositories?q={urllib.request.quote(query)}&sort=stars&per_page={capped_limit}"

        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        if github_token:
            req.add_header("Authorization", f"token {github_token}")

        response = urllib.request.urlopen(req, timeout=15)
        data = json.loads(response.read().decode("utf-8"))
        items = data.get("items", [])

        repos = []
        for item in items[:capped_limit]:
            repos.append({
                "repo_name": item.get("full_name", ""),
                "description": _shorten(item.get("description") or "", 200),
                "stars": item.get("stargazers_count", 0),
                "url": item.get("html_url", ""),
                "language": item.get("language") or "",
                "topics": item.get("topics", []),
            })

        summary_lines = []
        for index, repo in enumerate(repos, 1):
            line = f"{index}. {repo['repo_name']} ⭐{repo['stars']}"
            if repo.get("language"):
                line += f" [{repo['language']}]"
            if repo.get("description"):
                line += f"\n   {repo['description']}"
            line += f"\n   {repo['url']}"
            summary_lines.append(line)

        return ToolResult.success(data={
            "ok": True,
            "query": query,
            "num_results": len(repos),
            "repositories": repos,
            "summary": "\n\n".join(summary_lines),
        }).to_message_content()
    except Exception as exc:
        logger.error("search_github_repos failed: {}", exc)
        return ToolResult.failure(str(exc), "TOOL_FAILED").to_message_content()
