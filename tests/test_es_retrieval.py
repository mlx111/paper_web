"""Tests for the Elasticsearch BM25 retrieval service (third recall path).

Focus areas (no real ES needed):
1. ``rrf_fuse`` ranking math and metadata merge;
2. best-effort degradation: disabled / connection failure / query failure
   must never raise, just return empty or passthrough results.
"""

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.services.es_retrieval_service import ESRetrievalService, es_retrieval_service


def _doc(chunk_id: str, content: str = "") -> Document:
    return Document(page_content=content or f"content {chunk_id}", metadata={"chunk_id": chunk_id})


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------

class TestRRFFuse:
    def test_disjoint_lists_are_ranked_by_rrf_score(self):
        primary = [_doc("a"), _doc("b")]
        secondary = [_doc("c"), _doc("d")]
        fused = ESRetrievalService.rrf_fuse(primary, secondary, k=60)
        # rank0 of both lists tie at 1/60, rank1 tie at 1/61 (stable order)
        assert [d.metadata["chunk_id"] for d in fused] == ["a", "c", "b", "d"]
        scores = [d.metadata["score"] for d in fused]
        assert scores == sorted(scores, reverse=True)

    def test_overlap_gets_boosted_score(self):
        primary = [_doc("a"), _doc("b")]
        secondary = [_doc("b"), _doc("c")]
        fused = ESRetrievalService.rrf_fuse(primary, secondary, k=60)
        ids = [d.metadata["chunk_id"] for d in fused]
        # "b" appears in both lists -> rrf_hits == 2, ranks first or second
        assert ids.index("b") <= ids.index("a")
        b = next(d for d in fused if d.metadata["chunk_id"] == "b")
        assert b.metadata["rrf_hits"] == 2

    def test_rrf_score_math(self):
        primary = [_doc("a")]
        secondary = [_doc("a")]
        fused = ESRetrievalService.rrf_fuse(primary, secondary, k=60)
        # rank 0 in both lists: 1/60 + 1/60 = 1/30
        assert abs(fused[0].metadata["score"] - 1.0 / 30) < 1e-9

    def test_limit_truncates(self):
        primary = [_doc(f"p{i}") for i in range(5)]
        secondary = [_doc(f"s{i}") for i in range(5)]
        fused = ESRetrievalService.rrf_fuse(primary, secondary, k=60, limit=4)
        assert len(fused) == 4

    def test_empty_inputs_passthrough(self):
        only_primary = [_doc("a")]
        assert ESRetrievalService.rrf_fuse(only_primary, [], k=60) == only_primary
        only_secondary = [_doc("b")]
        assert ESRetrievalService.rrf_fuse([], only_secondary, k=60) == only_secondary
        assert ESRetrievalService.rrf_fuse([], [], k=60) == []


# ---------------------------------------------------------------------------
# Best-effort degradation
# ---------------------------------------------------------------------------

class TestDegradation:
    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.es_retrieval_service.config", MagicMock(ES_RETRIEVAL_ENABLED=False)
        )
        svc = ESRetrievalService()
        assert svc.bm25_search("query", top_k=5) == []
        assert svc.index_chunks([{"chunk_id": "x", "text": "t"}]) == 0

    def test_connection_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.es_retrieval_service.config",
            MagicMock(ES_RETRIEVAL_ENABLED=True, ES_HOST="http://localhost:9200", ES_INDEX="idx"),
        )
        svc = ESRetrievalService()
        with patch.object(svc, "_get_client", return_value=None):
            assert svc.bm25_search("query") == []
            assert svc.index_chunks([{"chunk_id": "x"}]) == 0
            assert svc.delete_by_source("f.pdf") == 0

    def test_bm25_query_failure_never_raises(self):
        svc = ESRetrievalService()
        broken = MagicMock()
        broken.search.side_effect = RuntimeError("es down")
        with patch.object(svc, "_get_client", return_value=broken), patch.object(
            svc, "_ensure_index", return_value=True
        ):
            assert svc.bm25_search("query") == []

    def test_index_chunk_without_chunk_id_skipped(self):
        import sys
        import types

        svc = ESRetrievalService()
        fake_es = MagicMock()
        fake_helpers = MagicMock()
        fake_helpers.bulk.return_value = (1, 0)
        fake_elasticsearch = types.ModuleType("elasticsearch")
        fake_elasticsearch.helpers = fake_helpers
        with patch.dict(sys.modules, {"elasticsearch": fake_elasticsearch}), patch.object(
            svc, "_get_client", return_value=fake_es
        ), patch.object(svc, "_ensure_index", return_value=True):
            written = svc.index_chunks([{"text": "no id"}, {"chunk_id": "ok", "text": "t"}])
            assert written == 1
            # only the row with chunk_id is sent
            actions = fake_helpers.bulk.call_args[0][1]
            assert len(actions) == 1
            assert actions[0]["_id"] == "ok"
            # vectors never leak into ES documents
            assert "dense_embedding" not in actions[0]["_source"]


# ---------------------------------------------------------------------------
# Search result shape (metadata parity with Milvus)
# ---------------------------------------------------------------------------

class TestBM25ResultShape:
    def test_hit_to_document_metadata(self):
        svc = ESRetrievalService()
        fake_es = MagicMock()
        fake_es.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "c1",
                        "_score": 12.5,
                        "_source": {
                            "text": "注意力机制",
                            "chunk_id": "c1",
                            "filename": "paper.pdf",
                            "chunk_level": 3,
                            "page_number": 2,
                        },
                    }
                ]
            }
        }
        with patch.object(svc, "_get_client", return_value=fake_es), patch.object(
            svc, "_ensure_index", return_value=True
        ):
            docs = svc.bm25_search("注意力", top_k=3, chunk_level=3)
        assert len(docs) == 1
        meta = docs[0].metadata
        assert meta["chunk_id"] == "c1"
        assert meta["score"] == 12.5
        assert meta["retrieval_source"] == "elasticsearch"
        assert meta["filename"] == "paper.pdf"
        # chunk_level filter is passed through to the ES query
        bool_q = fake_es.search.call_args.kwargs["query"]["bool"]
        assert {"term": {"chunk_level": 3}} in bool_q["filter"]


def test_singleton_available():
    assert isinstance(es_retrieval_service, ESRetrievalService)