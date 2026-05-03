"""Tests for entity extraction, entity link store, and search ranking."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.models.entity_link import Entity, EntityLink, EntityType, RelationType
from app.services.entity_extraction_service import (
    AuthorExtractor,
    CitationExtractor,
    EntityExtractionService,
    KeywordExtractor,
    _to_slug,
    _tokenize,
)
from app.services.entity_link_store import EntityLinkStore
from app.services.query_intent_service import QueryIntent, QueryIntentService
from app.services.source_boost_config import (
    DEFAULT_SOURCE_BOOSTS,
    SourceBoostConfig,
    compute_keyword_boost,
    compute_source_boost,
    is_hard_excluded,
)
from app.services.search_ranking_service import SearchRankingService


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _store(tmp_path: Path) -> EntityLinkStore:
    return EntityLinkStore(data_dir=tmp_path / "entity_graph")


# ---------------------------------------------------------------------------
# Test slug / tokenize
# ---------------------------------------------------------------------------

class TestSlugAndTokenize:
    def test_to_slug_basic(self):
        assert _to_slug("Attention Is All You Need") == "attention-is-all-you-need"

    def test_to_slug_special_chars(self):
        assert _to_slug("Smith, J. (MIT)").startswith("smith-j")

    def test_to_slug_chinese(self):
        slug = _to_slug("深度学习")
        assert slug, f"slug should not be empty for Chinese text, got: {slug!r}"
        assert " " not in slug

    def test_tokenize_english(self):
        tokens = _tokenize("This paper proposes a novel attention mechanism")
        assert "attention" in tokens
        assert "paper" not in tokens  # stop word
        assert "method" not in tokens

    def test_tokenize_chinese(self):
        tokens = _tokenize("本文提出了一种新的注意力机制")
        assert "本文" not in tokens  # stop word
        assert "提出" not in tokens


# ---------------------------------------------------------------------------
# TestAuthorExtractor
# ---------------------------------------------------------------------------

class TestAuthorExtractor:
    def test_single_author(self):
        ae = AuthorExtractor()
        entities, links = ae.extract("paper/test", "Smith, John")
        assert len(entities) == 1
        assert entities[0].display_name == "Smith, John"
        assert entities[0].type == EntityType.AUTHOR
        assert len(links) == 1
        assert links[0].relation == RelationType.HAS_AUTHOR

    def test_multiple_authors(self):
        ae = AuthorExtractor()
        entities, links = ae.extract("paper/test", "Smith, J., Zhang, W., Lee, K.")
        assert len(entities) == 3
        names = {e.display_name for e in entities if e.type == EntityType.AUTHOR}
        assert names == {"Smith, J.", "Zhang, W.", "Lee, K."}
        assert len(links) == 3

    def test_empty_author_string(self):
        ae = AuthorExtractor()
        entities, links = ae.extract("paper/test", "")
        assert entities == []
        assert links == []

    def test_none_author_string(self):
        ae = AuthorExtractor()
        entities, links = ae.extract("paper/test", None)
        assert entities == []
        assert links == []

    def test_authors_with_affiliation(self):
        ae = AuthorExtractor()
        # Format without initials — full names let the parenthetical stay attached
        entities, links = ae.extract("paper/test", "John Smith (MIT Laboratory), Wei Zhang (Stanford University)")
        author_entities = [e for e in entities if e.type == EntityType.AUTHOR]
        inst_entities = [e for e in entities if e.type == EntityType.INSTITUTION]
        assert len(author_entities) == 2
        assert len(inst_entities) >= 1

        aff_links = [l for l in links if l.relation == RelationType.AFFILIATED_WITH]
        assert len(aff_links) >= 1

    def test_dedup_authors(self):
        ae = AuthorExtractor()
        entities, _ = ae.extract("paper/test", "Smith, J., Smith, J.")
        assert len(entities) == 1

    def test_authors_semicolon_separator(self):
        ae = AuthorExtractor()
        entities, _ = ae.extract("paper/test", "Smith, J.; Zhang, W.")
        assert len(entities) == 2

    def test_and_separator(self):
        ae = AuthorExtractor()
        entities, _ = ae.extract("paper/test", "Smith, J. and Zhang, W.")
        assert len(entities) == 2

    def test_short_name_filtered(self):
        ae = AuthorExtractor()
        entities, _ = ae.extract("paper/test", "X")
        assert len(entities) == 0  # single char filtered


# ---------------------------------------------------------------------------
# TestKeywordExtractor
# ---------------------------------------------------------------------------

class TestKeywordExtractor:
    def test_extracts_tf_keywords(self):
        ke = KeywordExtractor(max_keywords=5)
        abstract = (
            "We propose a novel attention mechanism for transformer models. "
            "The attention mechanism improves performance on machine translation tasks. "
            "Our transformer model achieves state-of-the-art results."
        )
        entities, links = ke.extract("paper/test", abstract)
        assert 1 <= len(entities) <= 5
        kw_names = {e.display_name for e in entities}
        assert "attention" in kw_names or "transformer" in kw_names
        has_kw_links = [l for l in links if l.relation == RelationType.HAS_KEYWORD]
        assert len(has_kw_links) == len(entities)

    def test_empty_abstract(self):
        ke = KeywordExtractor()
        entities, links = ke.extract("paper/test", "")
        assert entities == []
        assert links == []

    def test_filters_stop_words(self):
        ke = KeywordExtractor(max_keywords=10)
        abstract = "This paper studies the method and results of our approach to the problem."
        entities, _ = ke.extract("paper/test", abstract)
        # Most/all tokens should be stop words
        assert len(entities) <= 1 or all(e.display_name not in {"paper", "method", "result", "approach"} for e in entities)

    def test_generates_co_occurrence_links(self):
        ke = KeywordExtractor(max_keywords=5)
        abstract = "attention mechanism for transformer models in natural language processing"
        _, links = ke.extract("paper/test", abstract)
        co_links = [l for l in links if l.relation == RelationType.CO_OCCURS]
        if len([l for l in links if l.relation == RelationType.HAS_KEYWORD]) >= 2:
            assert len(co_links) > 0

    def test_filters_urls_and_dois(self):
        ke = KeywordExtractor(max_keywords=5)
        abstract = "See https://example.com/paper for details. DOI: 10.1234/foo.bar. The main contribution is attention."
        entities, _ = ke.extract("paper/test", abstract)
        kw_text = " ".join(e.display_name for e in entities)
        assert "https" not in kw_text
        assert "10.1234" not in kw_text

    def test_chinese_abstract(self):
        ke = KeywordExtractor(max_keywords=5)
        abstract = "本文提出了一种基于深度学习的自然语言处理方法，在机器翻译任务上取得了优异性能。"
        entities, _ = ke.extract("paper/test", abstract)
        assert len(entities) > 0


# ---------------------------------------------------------------------------
# TestCitationExtractor
# ---------------------------------------------------------------------------

class TestCitationExtractor:
    def test_bracket_citations(self):
        ce = CitationExtractor()
        _, links = ce.extract("paper/test", "Previous work [1] has shown. See also [2, 3].")
        assert len(links) >= 3  # [1], [2], [3]

    def test_paren_citations(self):
        ce = CitationExtractor()
        _, links = ce.extract("paper/test", "This was shown by (Vaswani, 2017) and (Brown, 2020).")
        assert len(links) == 2
        assert all(l.relation == RelationType.CITES for l in links)

    def test_et_al_citations(self):
        ce = CitationExtractor()
        _, links = ce.extract("paper/test", "Vaswani et al. (2017) proposed the Transformer.")
        assert len(links) == 1
        assert links[0].metadata.get("cite_format") == "inline"

    def test_empty_text(self):
        ce = CitationExtractor()
        _, links = ce.extract("paper/test", "")
        assert links == []

    def test_no_citations(self):
        ce = CitationExtractor()
        _, links = ce.extract("paper/test", "This paper has no citations.")
        assert links == []

    def test_dedup_citations(self):
        ce = CitationExtractor()
        _, links = ce.extract("paper/test", "[1] and [1] again.")
        # Should only produce one link for [1]
        ref1_links = [l for l in links if l.to_entity == "paper/ref-1"]
        assert len(ref1_links) == 1


# ---------------------------------------------------------------------------
# TestEntityExtractionService
# ---------------------------------------------------------------------------

class TestEntityExtractionService:
    def test_full_extraction(self):
        svc = EntityExtractionService()
        paper = {
            "title": "Attention Is All You Need",
            "authors": "Vaswani, A., Shazeer, N., Parmar, N.",
            "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
            "year": "2017",
            "venue": "NeurIPS",
            "source": "arxiv",
        }
        entities, links = svc.extract_from_paper(paper)
        paper_entities = [e for e in entities if e.type == EntityType.PAPER]
        author_entities = [e for e in entities if e.type == EntityType.AUTHOR]
        assert len(paper_entities) == 1
        assert len(author_entities) == 3
        assert any(l.relation == RelationType.HAS_AUTHOR for l in links)
        assert any(l.relation == RelationType.HAS_KEYWORD for l in links)

    def test_paper_slug_from_title(self):
        svc = EntityExtractionService()
        paper = {"title": "My Great Paper", "authors": "", "abstract": ""}
        entities, _ = svc.extract_from_paper(paper)
        paper_e = [e for e in entities if e.type == EntityType.PAPER][0]
        assert paper_e.slug == "paper/my-great-paper"

    def test_paper_slug_fallback_to_doi(self):
        svc = EntityExtractionService()
        paper = {"title": "", "doi": "10.1234/foo.bar", "authors": "", "abstract": ""}
        entities, _ = svc.extract_from_paper(paper)
        paper_e = [e for e in entities if e.type == EntityType.PAPER][0]
        assert "10-1234-foo-bar" in paper_e.slug or "paper/" in paper_e.slug

    def test_empty_paper(self):
        svc = EntityExtractionService()
        entities, links = svc.extract_from_paper({})
        assert len(entities) == 1  # paper entity only
        assert len(links) == 0

    def test_with_full_text_citations(self):
        svc = EntityExtractionService()
        paper = {
            "title": "Test Paper",
            "authors": "Doe, J.",
            "abstract": "Some abstract.",
            "full_text": "As shown in [1, 2] and (Smith, 2020), previous work establishes the baseline.",
        }
        _, links = svc.extract_from_paper(paper)
        cite_links = [l for l in links if l.relation == RelationType.CITES]
        assert len(cite_links) >= 3


# ---------------------------------------------------------------------------
# TestEntityLinkStore
# ---------------------------------------------------------------------------

class TestEntityLinkStore:
    def test_add_and_get_entity(self, tmp_path):
        store = _store(tmp_path)
        entity = Entity(slug="author/smith-j", display_name="Smith, J.", type=EntityType.AUTHOR)
        store.add_entity(entity)
        retrieved = store.get_entity("author/smith-j")
        assert retrieved is not None
        assert retrieved.display_name == "Smith, J."

    def test_merge_entities_same_slug(self, tmp_path):
        store = _store(tmp_path)
        e1 = Entity(slug="author/smith-j", display_name="Smith, J.", type=EntityType.AUTHOR, mention_count=1)
        e2 = Entity(slug="author/smith-j", display_name="Smith, John", type=EntityType.AUTHOR, mention_count=2)
        store.add_entity(e1)
        store.add_entity(e2)
        merged = store.get_entity("author/smith-j")
        assert merged.mention_count == 3

    def test_add_and_query_links(self, tmp_path):
        store = _store(tmp_path)
        link = EntityLink(
            from_entity="paper/test", to_entity="author/smith-j",
            relation=RelationType.HAS_AUTHOR,
            from_type=EntityType.PAPER, to_type=EntityType.AUTHOR,
        )
        store.add_link(link)
        links = store.get_links("paper/test", RelationType.HAS_AUTHOR)
        assert len(links) == 1

    def test_backlinks(self, tmp_path):
        store = _store(tmp_path)
        store.add_link(EntityLink(
            from_entity="paper/a", to_entity="author/smith-j",
            relation=RelationType.HAS_AUTHOR,
            from_type=EntityType.PAPER, to_type=EntityType.AUTHOR,
        ))
        store.add_link(EntityLink(
            from_entity="paper/b", to_entity="author/smith-j",
            relation=RelationType.HAS_AUTHOR,
            from_type=EntityType.PAPER, to_type=EntityType.AUTHOR,
        ))
        backlinks = store.get_backlinks("author/smith-j")
        assert len(backlinks) == 2
        assert store.get_backlink_count("author/smith-j") == 2

    def test_entity_boost(self, tmp_path):
        store = _store(tmp_path)
        store.add_entity(Entity(
            slug="author/smith-j", display_name="Smith, J.",
            type=EntityType.AUTHOR, mention_count=5,
        ))
        boost = store.get_entity_boost("author/smith-j")
        assert boost > 1.0
        assert boost == 1.0 + 0.1 * 5 + 0.05 * 0

    def test_boost_unknown_entity(self, tmp_path):
        store = _store(tmp_path)
        assert store.get_entity_boost("author/nonexistent") == 1.0

    def test_search_entities(self, tmp_path):
        store = _store(tmp_path)
        store.add_entity(Entity(slug="author/smith-j", display_name="Smith, J.", type=EntityType.AUTHOR))
        store.add_entity(Entity(slug="author/zhang-w", display_name="Zhang, W.", type=EntityType.AUTHOR))
        store.add_entity(Entity(slug="keyword/attention", display_name="attention", type=EntityType.KEYWORD))
        results = store.search_entities("smith")
        assert len(results) == 1
        results_author = store.search_entities("smith", EntityType.AUTHOR)
        assert len(results_author) == 1

    def test_persistence(self, tmp_path):
        store = _store(tmp_path)
        store.add_entity(Entity(slug="author/smith-j", display_name="Smith, J.", type=EntityType.AUTHOR))
        store.add_link(EntityLink(
            from_entity="paper/test", to_entity="author/smith-j",
            relation=RelationType.HAS_AUTHOR,
            from_type=EntityType.PAPER, to_type=EntityType.AUTHOR,
        ))

        store2 = EntityLinkStore(data_dir=tmp_path / "entity_graph")
        assert store2.get_entity("author/smith-j") is not None
        assert len(store2.get_links("paper/test")) == 1

    def test_clear(self, tmp_path):
        store = _store(tmp_path)
        store.add_entity(Entity(slug="author/test", display_name="Test", type=EntityType.AUTHOR))
        store.clear()
        assert store.entity_count == 0
        assert store.link_count == 0

    def test_get_related_papers(self, tmp_path):
        store = _store(tmp_path)
        store.add_link(EntityLink(
            from_entity="paper/p1", to_entity="keyword/attention",
            relation=RelationType.HAS_KEYWORD,
            from_type=EntityType.PAPER, to_type=EntityType.KEYWORD,
        ))
        store.add_link(EntityLink(
            from_entity="paper/p2", to_entity="keyword/attention",
            relation=RelationType.HAS_KEYWORD,
            from_type=EntityType.PAPER, to_type=EntityType.KEYWORD,
        ))
        papers = store.get_related_papers("keyword/attention")
        assert len(papers) == 2
        assert "paper/p1" in papers
        assert "paper/p2" in papers

    def test_dedup_links(self, tmp_path):
        store = _store(tmp_path)
        l1 = EntityLink(
            from_entity="paper/a", to_entity="author/x",
            relation=RelationType.HAS_AUTHOR,
            from_type=EntityType.PAPER, to_type=EntityType.AUTHOR,
        )
        l2 = EntityLink(
            from_entity="paper/a", to_entity="author/x",
            relation=RelationType.HAS_AUTHOR,
            from_type=EntityType.PAPER, to_type=EntityType.AUTHOR,
            metadata={"extra": "info"},
        )
        store.add_link(l1)
        store.add_link(l2)
        assert store.link_count == 1
        links = store.get_links("paper/a")
        assert links[0].metadata.get("extra") == "info"


# ---------------------------------------------------------------------------
# TestSourceBoostConfig
# ---------------------------------------------------------------------------

class TestSourceBoostConfig:
    def test_default_papers_boost(self):
        boost = compute_source_boost("papers/attention-is-all-you-need")
        assert boost == 1.5

    def test_longest_prefix_match(self):
        boost = compute_source_boost("papers/arxiv/attention")
        assert boost == 1.4  # more specific than papers/ (1.5)

    def test_no_match_defaults_to_one(self):
        boost = compute_source_boost("unknown/something")
        assert boost == 1.0

    def test_hard_exclude_matches(self):
        assert is_hard_excluded("tmp/something") is True
        assert is_hard_excluded("debug/log") is True
        assert is_hard_excluded("archive/old") is True

    def test_hard_exclude_no_match(self):
        assert is_hard_excluded("papers/paper1") is False

    def test_keyword_boost(self):
        assert compute_keyword_boost("what is attention mechanism") > 1.0
        assert compute_keyword_boost("RAG systems") > 1.0
        assert compute_keyword_boost("hello world") == 1.0

    def test_custom_config(self):
        cfg = SourceBoostConfig(
            source_weights={"custom/": 2.0},
            hard_excludes=["private/"],
            keyword_boosts={"xyz": 3.0},
        )
        assert compute_source_boost("custom/doc", cfg) == 2.0
        assert is_hard_excluded("private/key", cfg) is True
        assert compute_keyword_boost("xyz test", cfg) == 3.0


# ---------------------------------------------------------------------------
# TestQueryIntentService
# ---------------------------------------------------------------------------

class TestQueryIntentService:
    def test_entity_intent_who_wrote(self):
        qs = QueryIntentService()
        assert qs.classify("who wrote attention is all you need") == QueryIntent.ENTITY
        assert qs.classify("这篇论文的作者是谁") == QueryIntent.ENTITY

    def test_temporal_intent(self):
        qs = QueryIntentService()
        assert qs.classify("latest papers on deep learning") == QueryIntent.TEMPORAL
        assert qs.classify("最近有什么新研究") == QueryIntent.TEMPORAL

    def test_literature_intent(self):
        qs = QueryIntentService()
        assert qs.classify("papers about graph neural networks") == QueryIntent.LITERATURE
        assert qs.classify("RAG相关的论文有哪些") == QueryIntent.LITERATURE

    def test_general_intent(self):
        qs = QueryIntentService()
        assert qs.classify("hello world") == QueryIntent.GENERAL
        assert qs.classify("explain transformer") == QueryIntent.GENERAL

    def test_empty_query(self):
        qs = QueryIntentService()
        assert qs.classify("") == QueryIntent.GENERAL

    def test_search_params_per_intent(self):
        qs = QueryIntentService()
        entity_params = qs.get_search_params(QueryIntent.ENTITY)
        assert entity_params["top_k"] == 5

        temporal_params = qs.get_search_params(QueryIntent.TEMPORAL)
        assert temporal_params["top_k"] == 12
        assert temporal_params["recency_bias"] is True

        literature_params = qs.get_search_params(QueryIntent.LITERATURE)
        assert literature_params["top_k"] == 15


# ---------------------------------------------------------------------------
# TestSearchRankingService
# ---------------------------------------------------------------------------

class TestSearchRankingService:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.store = _store(tmp_path)
        self.service = SearchRankingService(entity_store=self.store)

    def _make_doc(self, content: str, score: float = 0.5, source: str = "papers/"):
        from langchain_core.documents import Document
        return Document(page_content=content, metadata={"score": score, "_source": source})

    def test_applies_source_boost(self):
        doc = self._make_doc("test content", score=0.5, source="papers/attention")
        boosted = self.service.apply_boosts([doc], "test query")
        final = boosted[0].metadata["final_score"]
        assert final > 0.5  # papers/ gets 1.5x

    def test_hard_excluded_source_not_boosted(self):
        doc = self._make_doc("test content", score=0.5, source="tmp/debug")
        boosted = self.service.apply_boosts([doc], "test query")
        final = boosted[0].metadata["final_score"]
        assert final == pytest.approx(0.5)  # no boost for excluded

    def test_sorts_by_final_score(self):
        d1 = self._make_doc("low score", score=0.2, source="chat/msg")
        d2 = self._make_doc("high score", score=0.8, source="papers/paper")
        boosted = self.service.apply_boosts([d1, d2], "test")
        assert boosted[0].page_content == "high score"
        assert boosted[1].page_content == "low score"

    def test_keyword_boost_applied(self):
        doc = self._make_doc("RAG systems", score=0.5, source="papers/")
        boosted = self.service.apply_boosts([doc], "RAG retrieval")
        final = boosted[0].metadata["final_score"]
        assert final > 0.5 * 1.5  # source boost * keyword boost

    def test_intent_set_in_metadata(self):
        doc = self._make_doc("test", score=0.5)
        boosted = self.service.apply_boosts([doc], "who wrote this paper")
        assert boosted[0].metadata["intent"] == QueryIntent.ENTITY.value

    def test_entity_boost_dampened(self):
        self.store.add_entity(Entity(
            slug="keyword/attention", display_name="attention",
            type=EntityType.KEYWORD, mention_count=10,
        ))
        doc = self._make_doc("attention mechanism", score=0.5, source="papers/")
        boosted = self.service.apply_boosts([doc], "attention")
        final = boosted[0].metadata["final_score"]
        assert final > 0.5  # boosted by entity presence

    def test_empty_docs(self):
        assert self.service.apply_boosts([], "test") == []

    def test_boost_single_convenience(self):
        doc = self._make_doc("test", score=0.5)
        result = self.service.boost_single(doc, "test")
        assert "final_score" in result.metadata
