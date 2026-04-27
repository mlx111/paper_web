"""On-demand document parsing tool for DeepAgent."""

from __future__ import annotations

import json

from langchain_core.tools import tool
from loguru import logger

from services.document_parser_service import document_parser_service


def _dump(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(
    name_or_callable="extract_document_text",
    description=(
        "Extract text from an existing local document path for quick analysis. "
        "Supported file types: PDF, DOCX, HTML, TXT, Markdown. "
        "Use this for ad-hoc reading; uploaded files should still use the normal file RAG flow. "
        "Args: file_path, summary_length."
    ),
)
def extract_document_text(file_path: str, summary_length: int = 5000) -> str:
    try:
        return _dump(
            document_parser_service.extract_text_from_file(
                file_path=file_path,
                summary_length=summary_length,
            )
        )
    except Exception as exc:
        logger.error("extract_document_text failed: {}", exc)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": str(exc)})
