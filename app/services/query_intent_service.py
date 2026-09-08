"""Regex-based query intent classification — zero latency, zero LLM."""

from __future__ import annotations

import re
from enum import Enum


class QueryIntent(str, Enum):
    ENTITY = "entity"         # "这篇论文是谁写的", "Who wrote this paper"
    TEMPORAL = "temporal"     # "最近研究了什么", "latest papers"
    LITERATURE = "literature" # "RAG相关的论文有哪些", "papers about X"
    GENERAL = "general"       # default fallback


# Patterns are ordered — first match wins
_INTENT_RULES: list[tuple[QueryIntent, re.Pattern]] = [
    (QueryIntent.ENTITY, re.compile(
        r"(谁|哪个作者|作者是谁|谁写的|作者列表|第一作者|通讯作者|"
        r"who\s+wrote|who\s+is|author\s+of|first\s+author|"
        r"published|发表于|发表(在|于))",
        re.IGNORECASE,
    )),
    (QueryIntent.TEMPORAL, re.compile(
        r"(最近|最新|latest|recent|近[几数]年|去年|今年|"
        r"trend|进展|前沿|recently\s+published|new\s+papers)",
        re.IGNORECASE,
    )),
    (QueryIntent.LITERATURE, re.compile(
        r"(有哪些|哪些论文|找.*论文|找.*文献|论文.*有|文献.*有|"
        r"papers?\s+(about|on|related|regarding)|"
        r"literature\s+(about|on|of)|"
        r"(about|on)\s+.*papers?|"
        r"survey|综述|回顾|总结.*(文献|论文))",
        re.IGNORECASE,
    )),
]


class QueryIntentService:
    """Classify a query into one of four intent categories."""

    def classify(self, query: str) -> QueryIntent:
        if not query or not query.strip():
            return QueryIntent.GENERAL

        for intent, pattern in _INTENT_RULES:
            if pattern.search(query):
                return intent

        return QueryIntent.GENERAL

    def get_search_params(self, intent: QueryIntent) -> dict:
        """Return tuned search parameters for this intent type."""
        params: dict = {
            "top_k": 8,
            "source_boost": True,
            "recency_bias": False,
        }
        if intent == QueryIntent.ENTITY:
            params["top_k"] = 5
        elif intent == QueryIntent.TEMPORAL:
            params["top_k"] = 12
            params["recency_bias"] = True
        elif intent == QueryIntent.LITERATURE:
            params["top_k"] = 15
            params["source_boost"] = True
        return params
