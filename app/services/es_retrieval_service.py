"""Elasticsearch BM25 词法检索服务：RAG 第三路召回 + RRF 融合。

角色定位：与 Milvus 的 dense/sparse 向量检索并列为一路独立召回——
- 向量检索擅长语义泛化（同义改写），但对精确术语（模型名、缩写、
  数字、罕见实体）容易失焦；
- BM25 词法检索恰好相反：精确术语强、语义泛化弱。两路互补后用
  RRF（Reciprocal Rank Fusion）融合，不需要把两路分数归一到同一尺度。

设计约定：
- ES 中的 chunk 文档与 Milvus 记录一一对应（chunk_id 为 _id），由
  入库侧（mlivus_server_service.write_documents）同步双写；
- 全链路 best-effort：ES 未启用 / 库未安装 / 连接失败时返回空结果，
  检索链路自动退化为纯 Milvus，与多模态图像检索的降级策略一致；
- metadata 字段与 Milvus 输出完全对齐，下游 rerank / auto_merge /
  source boost 无需感知数据来源。
"""

from langchain_core.documents import Document
from loguru import logger

from settings.config import config


class ESRetrievalService:
    """ES 索引写入 + BM25 查询 + RRF 融合（惰性连接，失败降级）。"""

    def __init__(self) -> None:
        self.es = None
        self._index_ready = False
        logger.info("ES 检索服务初始化完成，等待首次使用时建立连接")

    # ---------------------------------------------------------- 连接与索引

    def _get_client(self):
        if not config.ES_RETRIEVAL_ENABLED:
            return None
        if self.es is not None:
            return self.es
        try:
            from elasticsearch import Elasticsearch

            self.es = Elasticsearch(
                config.ES_HOST,
                request_timeout=5,
                max_retries=1,
                retry_on_timeout=True,
            )
            if not self.es.ping():
                logger.warning("ES ping 失败，BM25 召回降级关闭: {}", config.ES_HOST)
                self.es = None
            else:
                logger.info("ES 连接初始化完成: {}", config.ES_HOST)
            return self.es
        except Exception as exc:
            logger.warning("ES 连接失败（BM25 召回降级关闭）: {}", exc)
            self.es = None
            return None

    def _ensure_index(self):
        if self._index_ready:
            return True
        es = self._get_client()
        if es is None:
            return False
        try:
            if not es.indices.exists(index=config.ES_INDEX):
                es.indices.create(
                    index=config.ES_INDEX,
                    mappings={
                        "properties": {
                            "text": {"type": "text"},
                            "filename": {
                                "type": "keyword",
                                "fields": {"txt": {"type": "text"}},
                            },
                            "file_type": {"type": "keyword"},
                            "file_path": {"type": "keyword"},
                            "page_number": {"type": "integer"},
                            "chunk_idx": {"type": "integer"},
                            "chunk_id": {"type": "keyword"},
                            "parent_chunk_id": {"type": "keyword"},
                            "root_chunk_id": {"type": "keyword"},
                            "chunk_level": {"type": "integer"},
                            "_source": {"type": "keyword"},
                            "_extension": {"type": "keyword"},
                            "_file_name": {"type": "keyword"},
                            "h1": {"type": "text"},
                            "h2": {"type": "text"},
                            "h3": {"type": "text"},
                            "start_index": {"type": "long"},
                        }
                    },
                )
                logger.info("ES 索引创建完成: {}", config.ES_INDEX)
            self._index_ready = True
            return True
        except Exception as exc:
            logger.warning("ES 索引创建失败（BM25 召回降级关闭）: {}", exc)
            return False

    # -------------------------------------------------------------- 写入

    def index_chunks(self, rows: list[dict]) -> int:
        """入库侧双写：chunk 行（与 Milvus insert_data 同构）批量写 ES。

        返回成功写入条数（0 = 未启用或失败，调用方不感知异常）。
        """
        if not rows:
            return 0
        es = self._get_client()
        if es is None or not self._ensure_index():
            return 0
        try:
            from elasticsearch import helpers

            actions = []
            for row in rows:
                chunk_id = str(row.get("chunk_id") or "")
                if not chunk_id:
                    continue
                actions.append(
                    {
                        "_op_type": "index",
                        "_index": config.ES_INDEX,
                        "_id": chunk_id,
                        "_source": {k: v for k, v in row.items() if k not in ("dense_embedding", "sparse_embedding")},
                    }
                )
            if not actions:
                return 0
            success, _ = helpers.bulk(es, actions, raise_on_error=False, stats_only=True)
            logger.info("ES 索引写入完成，成功 {} 条", success)
            return int(success or 0)
        except Exception as exc:
            logger.warning("ES 索引写入失败（不影响 Milvus 入库）: {}", exc)
            return 0

    def delete_by_source(self, file_path: str) -> int:
        """删除文档时同步清理 ES 中的 chunk（保持双写一致性）。"""
        if not file_path:
            return 0
        es = self._get_client()
        if es is None or not self._ensure_index():
            return 0
        try:
            resp = es.delete_by_query(
                index=config.ES_INDEX,
                query={"term": {"_source": file_path}},
                refresh=True,
            )
            deleted = int(resp.get("deleted", 0))
            if deleted:
                logger.info("ES 同步删除旧数据 {}，删除数量: {}", file_path, deleted)
            return deleted
        except Exception as exc:
            logger.warning("ES 删除旧数据失败 {}: {}", file_path, exc)
            return 0

    # -------------------------------------------------------------- 查询

    def bm25_search(self, query: str, top_k: int = 10, chunk_level: int | None = None) -> list[Document]:
        """BM25 词法召回，输出与 Milvus hybrid_retrieve 同构的 Document 列表。"""
        if not query or not query.strip():
            return []
        es = self._get_client()
        if es is None or not self._ensure_index():
            return []
        try:
            must = {
                "multi_match": {
                    "query": query,
                    "fields": ["text^2", "h1^3", "h2^2", "h3"],
                }
            }
            filters = []
            if chunk_level is not None:
                filters.append({"term": {"chunk_level": int(chunk_level)}})
            body_query = {"bool": {"must": [must]}}
            if filters:
                body_query["bool"]["filter"] = filters

            resp = es.search(
                index=config.ES_INDEX,
                query=body_query,
                size=top_k,
            )
            docs: list[Document] = []
            for hit in resp.get("hits", {}).get("hits", []):
                src = hit.get("_source", {}) or {}
                metadata = {
                    "id": hit.get("_id"),
                    "filename": src.get("filename", ""),
                    "file_type": src.get("file_type", ""),
                    "file_path": src.get("file_path", ""),
                    "page_number": src.get("page_number", 0),
                    "chunk_id": src.get("chunk_id", "") or hit.get("_id", ""),
                    "parent_chunk_id": src.get("parent_chunk_id", ""),
                    "root_chunk_id": src.get("root_chunk_id", ""),
                    "chunk_level": src.get("chunk_level", 0),
                    "chunk_idx": src.get("chunk_idx", 0),
                    "_source": src.get("_source", ""),
                    "_extension": src.get("_extension", ""),
                    "_file_name": src.get("_file_name", ""),
                    "h1": src.get("h1", ""),
                    "h2": src.get("h2", ""),
                    "h3": src.get("h3", ""),
                    "start_index": src.get("start_index", 0),
                    "score": hit.get("_score", 0.0),
                    "retrieval_source": "elasticsearch",
                }
                docs.append(Document(page_content=src.get("text", ""), metadata=metadata))
            logger.info("ES BM25 检索完成，返回 {} 条文档", len(docs))
            return docs
        except Exception as exc:
            logger.warning("ES BM25 检索失败（降级纯 Milvus 结果）: {}", exc)
            return []

    # -------------------------------------------------------------- 融合

    @staticmethod
    def rrf_fuse(
        primary: list[Document],
        secondary: list[Document],
        k: int = 60,
        limit: int | None = None,
    ) -> list[Document]:
        """Reciprocal Rank Fusion：融合两路（或以上）排名列表。

        - 以 chunk_id 为融合键，同 chunk 在多路命中时 RRF 分数累加；
        - 输入顺序即排名（第 1 个 rank=0），分数 = sum(1 / (k + rank))；
        - primary 在前：同分时偏向向量检索结果（语义路是主路）；
        - limit 截断输出（None = 不截断）。
        """
        if not secondary:
            return list(primary)
        if not primary:
            return list(secondary)

        fused: dict[str, dict] = {}
        for rank, doc in enumerate(primary):
            key = str((doc.metadata or {}).get("chunk_id") or id(doc))
            fused[key] = {"doc": doc, "score": 1.0 / (k + rank), "hits": 1}
        for rank, doc in enumerate(secondary):
            key = str((doc.metadata or {}).get("chunk_id") or id(doc))
            entry = fused.get(key)
            if entry is not None:
                entry["score"] += 1.0 / (k + rank)
                entry["hits"] += 1
            else:
                fused[key] = {"doc": doc, "score": 1.0 / (k + rank), "hits": 1}

        merged = sorted(fused.values(), key=lambda e: (-e["score"], -e["hits"]))
        docs = []
        for entry in merged:
            doc = entry["doc"]
            metadata = dict(doc.metadata or {})
            metadata["score"] = entry["score"]
            metadata["rrf_hits"] = entry["hits"]
            doc.metadata = metadata
            docs.append(doc)
        if limit is not None:
            docs = docs[:limit]
        logger.info("RRF 融合完成：{} + {} -> {} 条", len(primary), len(secondary), len(docs))
        return docs


es_retrieval_service = ESRetrievalService()