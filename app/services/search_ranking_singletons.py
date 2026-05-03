"""Search ranking singleton — shares the entity store for cumulative ranking boosts."""

from services.search_ranking_service import SearchRankingService
from services.entity_extraction_singletons import entity_link_store

search_ranking_service = SearchRankingService(entity_store=entity_link_store)
