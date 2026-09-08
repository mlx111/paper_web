"""JSON-file based entity and link store — no database required."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models.entity_link import Entity, EntityLink, EntityType, RelationType


class EntityLinkStore:
    """Lightweight in-memory store backed by JSON files on disk.

    Stores:
    - entities: slug → Entity (entities.json)
    - links: list[EntityLink] (entity_links.json)

    All mutations are immediately persisted.
    """

    def __init__(self, data_dir: str | Path = ""):
        if not data_dir:
            data_dir = Path.cwd() / "app" / "data" / "entity_graph"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.entities_file = self.data_dir / "entities.json"
        self.links_file = self.data_dir / "entity_links.json"

        self._entities: dict[str, Entity] = {}
        self._links: list[EntityLink] = []
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self.entities_file.exists():
            try:
                raw = json.loads(self.entities_file.read_text(encoding="utf-8"))
                self._entities = {
                    slug: Entity(**data) for slug, data in raw.items()
                }
            except (json.JSONDecodeError, TypeError):
                self._entities = {}

        if self.links_file.exists():
            try:
                raw_list = json.loads(self.links_file.read_text(encoding="utf-8"))
                self._links = [EntityLink(**item) for item in raw_list]
            except (json.JSONDecodeError, TypeError):
                self._links = []

    def _save_entities(self) -> None:
        data = {slug: entity.model_dump() for slug, entity in self._entities.items()}
        self.entities_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _save_links(self) -> None:
        data = [link.model_dump() for link in self._links]
        self.links_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # entity CRUD
    # ------------------------------------------------------------------

    def add_entity(self, entity: Entity) -> None:
        existing = self._entities.get(entity.slug)
        if existing:
            existing.mention_count += entity.mention_count
            existing.metadata.update(entity.metadata)
        else:
            self._entities[entity.slug] = entity
        self._save_entities()

    def add_entities(self, entities: list[Entity]) -> None:
        for e in entities:
            self.add_entity(e)

    def get_entity(self, slug: str) -> Entity | None:
        return self._entities.get(slug)

    def search_entities(
        self, query: str, entity_type: EntityType | None = None
    ) -> list[Entity]:
        q = query.strip().lower()
        results: list[Entity] = []
        for entity in self._entities.values():
            if entity_type and entity.type != entity_type:
                continue
            if q in entity.display_name.lower() or q in entity.slug:
                results.append(entity)
        results.sort(key=lambda e: e.mention_count, reverse=True)
        return results

    # ------------------------------------------------------------------
    # link CRUD
    # ------------------------------------------------------------------

    def add_link(self, link: EntityLink) -> None:
        key = (link.from_entity, link.to_entity, link.relation.value)
        for existing in self._links:
            ek = (existing.from_entity, existing.to_entity, existing.relation.value)
            if ek == key:
                existing.metadata.update(link.metadata)
                self._save_links()
                return
        self._links.append(link)
        self._save_links()

    def add_links(self, links: list[EntityLink]) -> None:
        for link in links:
            self.add_link(link)

    def get_links(
        self, slug: str, relation: RelationType | None = None
    ) -> list[EntityLink]:
        results: list[EntityLink] = []
        for link in self._links:
            if link.from_entity != slug:
                continue
            if relation and link.relation != relation:
                continue
            results.append(link)
        return results

    def get_backlinks(self, slug: str) -> list[EntityLink]:
        return [link for link in self._links if link.to_entity == slug]

    def get_backlink_count(self, slug: str) -> int:
        return sum(1 for link in self._links if link.to_entity == slug)

    # ------------------------------------------------------------------
    # graph queries
    # ------------------------------------------------------------------

    def get_entity_boost(self, slug: str) -> float:
        """Boost factor based on mention_count + backlink count."""
        entity = self._entities.get(slug)
        if not entity:
            return 1.0
        return 1.0 + 0.1 * min(entity.mention_count, 10) + 0.05 * min(self.get_backlink_count(slug), 20)

    def get_related_papers(self, slug: str, max_results: int = 5) -> list[str]:
        """Find papers connected to an entity slug via any link."""
        paper_slugs: set[str] = set()
        for link in self._links:
            if link.to_entity == slug and link.from_type == EntityType.PAPER:
                paper_slugs.add(link.from_entity)
            elif link.from_entity == slug and link.to_type == EntityType.PAPER:
                paper_slugs.add(link.to_entity)
            elif (
                link.from_entity == slug
                and link.relation == RelationType.CO_OCCURS
            ):
                for inner in self._links:
                    if (
                        inner.to_entity == link.to_entity
                        and inner.from_type == EntityType.PAPER
                    ):
                        paper_slugs.add(inner.from_entity)
        return list(paper_slugs)[:max_results]

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def link_count(self) -> int:
        return len(self._links)

    def clear(self) -> None:
        self._entities.clear()
        self._links.clear()
        self._save_entities()
        self._save_links()
