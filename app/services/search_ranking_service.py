"""Search ranking enhancement: source boost + entity boost on top of reranker scores."""

from __future__ import annotations

from typing import Any

import jieba

from langchain_core.documents import Document

from models.entity_link import EntityType
from services.entity_link_store import EntityLinkStore
from services.source_boost_config import (
    DEFAULT_SOURCE_BOOSTS,
    SourceBoostConfig,
    compute_keyword_boost,
    compute_source_boost,
    is_hard_excluded,
)
from services.query_intent_service import QueryIntentService


class SearchRankingService:
    """Apply source and entity boosts to rerank scores."""

    def __init__(
        self,
        entity_store: EntityLinkStore | None = None,
        source_config: SourceBoostConfig | None = None,
        intent_service: QueryIntentService | None = None,
    ):
        self.entity_store = entity_store
        self.source_config = source_config or DEFAULT_SOURCE_BOOSTS
        self.intent_service = intent_service or QueryIntentService()

    def apply_boosts(
        self, docs: list[Document], query: str
    ) -> list[Document]:
        """Boost and re-sort documents. Returns new list (does not mutate input)."""
        if not docs:
            return []

        intent = self.intent_service.classify(query)
        kw_boost = compute_keyword_boost(query, self.source_config)

        for doc in docs:
            metadata = doc.metadata or {}
            score = float(metadata.get("rerank_score", metadata.get("score", 0.5)))

            # Source boost (longest prefix match on _source or filename)
            source = str(metadata.get("_source", metadata.get("filename", "")))
            if source and not is_hard_excluded(source, self.source_config):
                score *= compute_source_boost(source, self.source_config)

            # Keyword boost from query
            if kw_boost > 1.0:
                score *= kw_boost

            # Entity boost (dampened)
            if self.entity_store:
                tokens = [t.strip().lower() for t in jieba.cut(query) if len(t.strip()) >= 2]
                for token in tokens:
                    entity_boost = self.entity_store.get_entity_boost(f"keyword/{token}")
                    if entity_boost > 1.0:
                        score *= (1.0 + (entity_boost - 1.0) * 0.3)

            metadata["intent"] = intent.value
            metadata["final_score"] = score

        docs.sort(key=lambda d: (d.metadata or {}).get("final_score", 0), reverse=True)
        return docs

    def boost_single(self, doc: Document, query: str) -> Document:
        """Apply boosts to a single document (convenience wrapper)."""
        boosted = self.apply_boosts([doc], query)
        return boosted[0] if boosted else doc
