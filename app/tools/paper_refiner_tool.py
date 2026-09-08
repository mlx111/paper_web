"""Paper refiner tools for review and citation pool generation."""

from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from services.paper_refiner_service import paper_refiner_service
from .tool_result import ToolResult


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
        data = paper_refiner_service.review_paper_quality(paper_text, title)
        return ToolResult.success(data=data).to_message_content()
    except Exception as exc:
        logger.error("review_paper_quality failed: {}", exc)
        return ToolResult.failure(str(exc), "TOOL_FAILED").to_message_content()


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
        data = paper_refiner_service.build_citation_pool(
            topic=topic,
            max_papers=max_papers,
            engine=engine,
            include_bibtex=include_bibtex,
        )
        return ToolResult.success(data=data).to_message_content()
    except Exception as exc:
        logger.error("build_citation_pool failed: {}", exc)
        return ToolResult.failure(str(exc), "TOOL_FAILED").to_message_content()
