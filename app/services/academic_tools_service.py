"""Academic paper search and citation helpers."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover - exercised only in minimal test envs
    requests = None  # type: ignore[assignment]


HttpGet = Callable[..., Any]


def _ok(**payload: Any) -> dict[str, Any]:
    return {"ok": True, **payload}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.replace("\x00", "").strip()


def _openalex_abstract_text(work: dict[str, Any]) -> str:
    inverted = work.get("abstract_inverted_index") or {}
    tokens: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for position in positions or []:
            try:
                tokens.append((int(position), str(word)))
            except (TypeError, ValueError):
                continue
    tokens.sort(key=lambda item: item[0])
    return " ".join(word for _, word in tokens).strip()


class AcademicToolsService:
    """Small service adapted from AgentSPEX academic tools.

    The service stays framework-free so it can be used by FastAPI routes,
    LangChain tools, and tests without pulling in AgentSPEX's MCP sandbox.
    """

    def __init__(self, http_get: HttpGet | None = None):
        if http_get is not None:
            self.http_get = http_get
        elif requests is not None:
            self.http_get = requests.get
        else:
            self.http_get = self._missing_requests_get

    @staticmethod
    def _missing_requests_get(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("requests is required for academic network tools")

    def search_papers(
        self,
        query: str,
        result_limit: int = 10,
        engine: str = "openalex",
        min_year: Optional[int] = None,
        s2_api_key: Optional[str] = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            return _err("INVALID_INPUT", "query must be a non-empty string")

        result_limit = max(1, min(int(result_limit or 10), 30))
        engine = (engine or "openalex").strip().lower()
        s2_api_key = s2_api_key or os.getenv("S2_API_KEY")

        if engine == "auto":
            try:
                papers = self._search_openalex(query, result_limit, min_year=min_year)
            except Exception:
                papers = []
            if not papers:
                try:
                    papers = self._search_semanticscholar(query, result_limit, s2_api_key, min_year=min_year)
                except Exception:
                    papers = []
            if not papers:
                try:
                    papers = self._search_arxiv(query, result_limit, min_year=min_year)
                except Exception:
                    papers = []
        elif engine == "openalex":
            papers = self._search_openalex(query, result_limit, min_year=min_year)
        elif engine == "semanticscholar":
            papers = self._search_semanticscholar(query, result_limit, s2_api_key, min_year=min_year)
            if not papers:
                papers = self._search_openalex(query, result_limit, min_year=min_year)
        elif engine == "arxiv":
            papers = self._search_arxiv(query, result_limit, min_year=min_year)
        else:
            return _err("INVALID_ENGINE", f"unknown engine: {engine}")

        return _ok(
            query=query,
            engine=engine,
            num_results=len(papers),
            papers=papers,
            formatted=self._format_paper_results(papers),
        )

    def get_bibtex_from_url(self, url: str, title: str) -> dict[str, Any]:
        if not title or not title.strip():
            return _err("INVALID_INPUT", "title must be a non-empty string")
        if not url or not url.startswith(("http://", "https://")):
            return _err("INVALID_URL", "url must start with http:// or https://")

        doi = self._doi_from_url(url)
        if not doi:
            doi = self._crossref_search_doi_by_title(title)
        if not doi:
            return _err("DOI_NOT_FOUND", "could not resolve DOI from url or title")

        response = self.http_get(
            f"https://doi.org/{doi}",
            headers={"Accept": "application/x-bibtex"},
            timeout=10,
        )
        if getattr(response, "status_code", 0) == 200:
            return _ok(doi=doi, bibtex=(response.text or "").replace("\n", ""))
        return _err("FETCH_FAILED", f"BibTeX request failed for DOI {doi}")

    def get_abstract_from_url(self, url: str, title: str) -> dict[str, Any]:
        if not title or not title.strip():
            return _err("INVALID_INPUT", "title must be a non-empty string")
        if not url or not url.startswith(("http://", "https://")):
            return _err("INVALID_URL", "url must start with http:// or https://")

        doi = self._doi_from_url(url) or self._crossref_search_doi_by_title(title)
        if not doi:
            return _err("DOI_NOT_FOUND", "could not resolve DOI from url or title")

        abstract = self._openalex_abstract_by_doi(doi)
        if abstract:
            return _ok(doi=doi, abstract=abstract)

        abstract = self._crossref_abstract(doi)
        if abstract:
            return _ok(doi=doi, abstract=abstract)

        return _ok(doi=doi, abstract=None)

    @staticmethod
    def _paper_year_value(paper: dict[str, Any]) -> int:
        raw_year = paper.get("year", "")
        try:
            return int(str(raw_year)[:4])
        except Exception:
            return -1

    def _prefer_recent_papers(
        self,
        papers: list[dict[str, Any]],
        result_limit: int,
        min_year: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        if not papers:
            return []

        ranked = sorted(
            papers,
            key=lambda paper: (
                self._paper_year_value(paper),
                int(paper.get("citation_count", 0) or 0),
            ),
            reverse=True,
        )
        if min_year is not None:
            filtered = [paper for paper in ranked if self._paper_year_value(paper) >= int(min_year)]
            if filtered:
                return filtered[:result_limit]
        return ranked[:result_limit]

    def _search_openalex(self, query: str, result_limit: int, min_year: Optional[int] = None) -> list[dict[str, Any]]:
        mail = os.getenv("OPENALEX_MAIL_ADDRESS") or os.getenv("OPENALEX_EMAIL")
        headers = {"User-Agent": f"mailto:{mail}" if mail else "MyPaperWeb/1.0"}
        fetch_limit = min(max(result_limit * 3, result_limit), 25)
        response = self.http_get(
            "https://api.openalex.org/works",
            headers=headers,
            params={"search": query, "per_page": fetch_limit},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json() or {}

        papers: list[dict[str, Any]] = []
        for work in (data.get("results") or [])[:result_limit]:
            location = work.get("primary_location") or {}
            source = location.get("source") or {}
            authors = ", ".join(
                _sanitize_text(item.get("author", {}).get("display_name", ""))
                for item in work.get("authorships", [])
                if item.get("author", {}).get("display_name")
            )
            papers.append(
                {
                    "title": _sanitize_text(work.get("title")),
                    "abstract": _sanitize_text(
                        work.get("abstract") or _openalex_abstract_text(work)
                    ),
                    "authors": authors,
                    "venue": _sanitize_text(source.get("display_name")),
                    "year": work.get("publication_year", ""),
                    "citation_count": work.get("cited_by_count", 0),
                    "url": location.get("landing_page_url") or work.get("id") or "",
                    "doi": work.get("doi") or "",
                    "source": "openalex",
                }
            )
        return self._prefer_recent_papers(papers, result_limit, min_year=min_year)

    def _search_semanticscholar(
        self, query: str, result_limit: int, s2_api_key: Optional[str], min_year: Optional[int] = None
    ) -> list[dict[str, Any]]:
        headers = {"User-Agent": "MyPaperWeb/1.0", "Accept": "application/json"}
        if s2_api_key:
            headers["x-api-key"] = s2_api_key
        fetch_limit = max(result_limit * 3, result_limit)
        response = self.http_get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            headers=headers,
            params={
                "query": query,
                "limit": fetch_limit,
                "fields": "title,authors,venue,year,abstract,citationCount,paperId,url",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json() or {}

        papers: list[dict[str, Any]] = []
        for paper in (data.get("data") or [])[:result_limit]:
            authors = ", ".join(
                _sanitize_text(author.get("name", ""))
                for author in paper.get("authors", [])
                if author.get("name")
            )
            papers.append(
                {
                    "title": _sanitize_text(paper.get("title")),
                    "abstract": _sanitize_text(paper.get("abstract")),
                    "authors": authors,
                    "venue": _sanitize_text(paper.get("venue")),
                    "year": paper.get("year", ""),
                    "citation_count": paper.get("citationCount", 0),
                    "url": paper.get("url") or "",
                    "doi": "",
                    "source": "semanticscholar",
                }
            )
        return self._prefer_recent_papers(papers, result_limit, min_year=min_year)

    def _search_arxiv(self, query: str, result_limit: int, min_year: Optional[int] = None) -> list[dict[str, Any]]:
        response = self.http_get(
            "http://export.arxiv.org/api/query",
            params={"search_query": query, "start": 0, "max_results": max(result_limit * 3, result_limit)},
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}

        papers: list[dict[str, Any]] = []
        for entry in root.findall("atom:entry", namespace):
            title = entry.findtext("atom:title", default="", namespaces=namespace)
            summary = entry.findtext("atom:summary", default="", namespaces=namespace)
            url = entry.findtext("atom:id", default="", namespaces=namespace)
            published = entry.findtext("atom:published", default="", namespaces=namespace)
            authors = [
                _sanitize_text(author.findtext("atom:name", default="", namespaces=namespace))
                for author in entry.findall("atom:author", namespace)
            ]
            papers.append(
                {
                    "title": _sanitize_text(title),
                    "abstract": _sanitize_text(summary),
                    "authors": ", ".join(author for author in authors if author),
                    "venue": "arXiv",
                    "year": published[:4] if published else "",
                    "citation_count": 0,
                    "url": url,
                    "doi": self._doi_from_url(url) or "",
                    "source": "arxiv",
                }
            )
        return self._prefer_recent_papers(papers, result_limit, min_year=min_year)

    def _openalex_abstract_by_doi(self, doi: str) -> str:
        email = os.getenv("OPENALEX_EMAIL") or os.getenv("OPENALEX_MAIL_ADDRESS")
        response = self.http_get(
            f"https://api.openalex.org/works/https://doi.org/{doi}",
            params={"mailto": email} if email else None,
            timeout=10,
        )
        if getattr(response, "status_code", 0) != 200:
            return ""
        return _openalex_abstract_text(response.json() or {})

    def _crossref_abstract(self, doi: str) -> str:
        response = self.http_get(f"https://api.crossref.org/works/{doi}", timeout=10)
        if getattr(response, "status_code", 0) != 200:
            return ""
        message = (response.json() or {}).get("message") or {}
        return _sanitize_text(message.get("abstract"))

    def _crossref_search_doi_by_title(self, title: str) -> str:
        response = self.http_get(
            "https://api.crossref.org/works",
            params={"query.title": title, "rows": 1},
            timeout=10,
        )
        if getattr(response, "status_code", 0) not in {0, 200}:
            return ""
        items = ((response.json() or {}).get("message") or {}).get("items") or []
        return _sanitize_text(items[0].get("DOI")) if items else ""

    def _doi_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        if "arxiv.org" in parsed.netloc:
            arxiv_id = parsed.path.strip("/").split("/")[-1].replace(".pdf", "")
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            return f"10.48550/arXiv.{arxiv_id}" if arxiv_id else ""

        match = re.search(r"\b10\.\d{4,9}/[^\s\"<>]+", url)
        if match:
            return match.group(0).rstrip(").,;")
        return ""

    @staticmethod
    def _format_paper_results(papers: list[dict[str, Any]]) -> str:
        if not papers:
            return "No papers found."
        lines: list[str] = []
        for index, paper in enumerate(papers, 1):
            parts = [
                f"{index}. {paper.get('title', '')}",
                f"Authors: {paper.get('authors', '')}",
                f"Venue/Year: {paper.get('venue', '')} {paper.get('year', '')}".strip(),
                f"Citations: {paper.get('citation_count', 0)}",
            ]
            if paper.get("url"):
                parts.append(f"URL: {paper.get('url')}")
            if paper.get("abstract"):
                abstract = str(paper["abstract"])
                if len(abstract) > 1600:
                    abstract = abstract[:1600] + "..."
                parts.append(f"Abstract: {abstract}")
            lines.append("\n".join(parts))
        return "\n\n".join(lines)


academic_tools_service = AcademicToolsService()
