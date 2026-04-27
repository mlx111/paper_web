"""Paper refiner tools for review and citation pool generation."""

from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

from services.paper_refiner_service import paper_refiner_service


def _dump(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(
    name_or_callable="review_paper_quality",
    description=(
        "Review a paper or paper excerpt like a lightweight reviewer. "
        "Use this for novelty, significance, soundness, strengths, weaknesses, and revision suggestions. "
        "Args: paper_text, title."
    ),
)
def review_paper_quality(paper_text: str, title: str = "") -> str:
    try:
        return _dump(paper_refiner_service.review_paper_quality(paper_text, title))
    except Exception as exc:
        logger.error("review_paper_quality failed: {}", exc)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": str(exc)})


@tool(
    name_or_callable="build_citation_pool",
    description=(
        "Build a citation pool for a topic, abstract, or paper excerpt by searching related academic papers. "
        "Use this for related work, recommended references, or citation suggestions. "
        "Args: topic, max_papers, engine, include_bibtex."
    ),
)
def build_citation_pool(
    topic: str,
    max_papers: int = 5,
    engine: str = "openalex",
    include_bibtex: bool = False,
) -> str:
    try:
        return _dump(
            paper_refiner_service.build_citation_pool(
                topic=topic,
                max_papers=max_papers,
                engine=engine,
                include_bibtex=include_bibtex,
            )
        )
    except Exception as exc:
        logger.error("build_citation_pool failed: {}", exc)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": str(exc)})
