"""Entity extraction singletons — shared store and extractor for cross-service use."""

from services.entity_link_store import EntityLinkStore
from services.entity_extraction_service import EntityExtractionService

entity_link_store = EntityLinkStore()
entity_extraction_service = EntityExtractionService()
