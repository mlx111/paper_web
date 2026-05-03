"""Entity and link models for the zero-LLM knowledge graph."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    AUTHOR = "author"
    INSTITUTION = "institution"
    KEYWORD = "keyword"
    PAPER = "paper"
    TOPIC = "topic"


class RelationType(str, Enum):
    CITES = "cites"
    HAS_AUTHOR = "has_author"
    AFFILIATED_WITH = "affiliated"
    HAS_KEYWORD = "has_keyword"
    CO_OCCURS = "co_occurs"
    PUBLISHED_IN = "published_in"


class Entity(BaseModel):
    slug: str
    display_name: str
    type: EntityType
    mention_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityLink(BaseModel):
    from_entity: str
    to_entity: str
    relation: RelationType
    from_type: EntityType
    to_type: EntityType
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
