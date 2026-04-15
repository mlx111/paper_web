from langchain_core.documents import Document
from loguru import logger
from pymilvus import AnnSearchRequest, DataType, MilvusClient, RRFRanker

from settings.config import config


class MilvusManager:
    def __init__(self) -> None:
        self.uri = f"http://{config.MILVUS_HOST}:{config.MILVUS_PORT}"
        self.client: MilvusClient | None = None
        logger.info("Milvus 客户端管理器初始化完成，等待首次使用时建立连接")

    def connect(self) -> MilvusClient:
        try:
            client = self._get_client()
            logger.info("Milvus 连接初始化完成: {}", self.uri)
            return client
        except Exception as exc:
            logger.error("Milvus 连接初始化失败: {}", exc)
            raise

    def _get_client(self) -> MilvusClient:
        if self.client is None:
            self.client = MilvusClient(self.uri)
            logger.info("Milvus 客户端连接完成: {}", self.uri)
        return self.client

    def _get_collection_dense_dim(self, client: MilvusClient) -> int | None:
        try:
            collection_info = client.describe_collection(collection_name=config.MILVUS_COLLECTION)
            if isinstance(collection_info, dict):
                fields = collection_info.get("schema", {}).get("fields", []) or collection_info.get("fields", [])
            else:
                current_dim = self._get_collection_dense_dim(client)
                if current_dim is not None and int(current_dim) != int(dense_dim):
                    raise ValueError(
                        f"Milvus collection '{config.MILVUS_COLLECTION}' 的 dense_embedding 维度为 {current_dim}，"
                        f"与当前配置 {dense_dim} 不一致。请删除旧 collection 或更换 MILVUS_COLLECTION 后重建。"
                    )
                schema = getattr(collection_info, "schema", None)
                fields = getattr(schema, "fields", []) if schema is not None else []

            for field in fields:
                if isinstance(field, dict) and field.get("name") == "dense_embedding":
                    params = field.get("params", {}) or {}
                    dim = params.get("dim") or field.get("dim")
                    if dim is not None:
                        return int(dim)
            return None
        except Exception as exc:
            logger.warning("Milvus 读取集合维度失败，跳过维度检查: {}", exc)
            return None

    def init_collection(self, dense_dim: int = None):
        try:
            client = self._get_client()
            dense_dim = dense_dim or config.EMBEDDING_DIM
            if not client.has_collection(config.MILVUS_COLLECTION):
                schema = client.create_schema(auto_id=True, enable_dynamic_field=True)
                schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
                schema.add_field("dense_embedding", DataType.FLOAT_VECTOR, dim=dense_dim)
                schema.add_field("sparse_embedding", DataType.SPARSE_FLOAT_VECTOR)
                schema.add_field("text", DataType.VARCHAR, max_length=16384)
                schema.add_field("filename", DataType.VARCHAR, max_length=255)
                schema.add_field("file_type", DataType.VARCHAR, max_length=50)
                schema.add_field("file_path", DataType.VARCHAR, max_length=1024)
                schema.add_field("page_number", DataType.INT64)
                schema.add_field("chunk_idx", DataType.INT64)
                schema.add_field("chunk_id", DataType.VARCHAR, max_length=512)
                schema.add_field("parent_chunk_id", DataType.VARCHAR, max_length=512)
                schema.add_field("root_chunk_id", DataType.VARCHAR, max_length=512)
                schema.add_field("chunk_level", DataType.INT64)
                schema.add_field("_source", DataType.VARCHAR, max_length=1024)
                schema.add_field("_extension", DataType.VARCHAR, max_length=32)
                schema.add_field("_file_name", DataType.VARCHAR, max_length=255)
                schema.add_field("h1", DataType.VARCHAR, max_length=512)
                schema.add_field("h2", DataType.VARCHAR, max_length=512)
                schema.add_field("h3", DataType.VARCHAR, max_length=512)
                schema.add_field("start_index", DataType.INT64)
                
                index_params = client.prepare_index_params()
                index_params.add_index(
                    field_name="dense_embedding",
                    index_type="HNSW",
                    metric_type="IP",
                    params={"M": 16, "efConstruction": 256},
                )
                index_params.add_index(
                    field_name="sparse_embedding",
                    index_type="SPARSE_INVERTED_INDEX",
                    metric_type="IP",
                    params={"drop_ratio_build": 0.2},
                )

                client.create_collection(
                    collection_name=config.MILVUS_COLLECTION,
                    schema=schema,
                    index_params=index_params,
                )
                logger.info("Milvus 集合创建完成: {}", config.MILVUS_COLLECTION)
            else:
                logger.info("Milvus 集合已存在: {}", config.MILVUS_COLLECTION)
        except Exception as exc:
            logger.error("初始化 Milvus 集合失败: {}", exc)
            raise

    def insert(self, data: list[dict]):
        try:
            client = self._get_client()
            client.insert(config.MILVUS_COLLECTION, data)
            logger.info("Milvus 写入完成，记录数: {}", len(data))
        except Exception as exc:
            logger.error("Milvus 写入失败: {}", exc)
            raise

    def query(self, filter_expr="", output_filed: list[str] = None, limit=10000):
        try:
            client = self._get_client()
            result = client.query(
                collection_name=config.MILVUS_COLLECTION,
                filter=filter_expr,
                output_fields=output_filed or ["filename", "file_type"],
                limit=limit,
            )
            logger.info("Milvus 普通查询完成，返回 {} 条记录", len(result))
            return result
        except Exception as exc:
            logger.error("Milvus 普通查询失败: {}", exc)
            raise

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[dict]:
        try:
            ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
            if not ids:
                logger.info("按 ID 获取分块完成，输入为空")
                return []

            query_id = ", ".join([f'"{item}"' for item in ids])
            filter_expr = f"chunk_id in [{query_id}]"
            client = self._get_client()
            result = client.query(
                collection_name=config.MILVUS_COLLECTION,
                filter=filter_expr,
                output_fields=[
                    "text",
                    "filename",
                    "file_type",
                    "file_path",
                    "page_number",
                    "chunk_id",
                    "parent_chunk_id",
                    "root_chunk_id",
                    "chunk_level",
                    "chunk_idx",
                    "_source",
                    "_extension",
                    "_file_name",
                    "h1",
                    "h2",
                    "h3",
                    "start_index",
                ],
                limit=len(ids),
            )
            logger.info("按 ID 获取分块完成，命中 {} 条", len(result))
            return result
        except Exception as exc:
            logger.error("按 ID 获取分块失败: {}", exc)
            raise

    def hybrid_retrieve(
        self,
        dense_embedding: list[float],
        sparse_embedding: dict,
        top_k: int = 5,
        rrf_k: int = 60,
        filter_expr: str = "",
    ) -> list[Document]:
        try:
            output_fields = [
                "text",
                "filename",
                "file_type",
                "file_path",
                "page_number",
                "chunk_id",
                "parent_chunk_id",
                "root_chunk_id",
                "chunk_level",
                "chunk_idx",
                "_source",
                "_extension",
                "_file_name",
                "h1",
                "h2",
                "h3",
                "start_index",
            ]
            dense_search = AnnSearchRequest(
                data=[dense_embedding],
                anns_field="dense_embedding",
                param={"metric_type": "IP", "params": {"ef": 64}},
                limit=top_k * 2,
                expr=filter_expr,
            )
            sparse_search = AnnSearchRequest(
                data=[sparse_embedding],
                anns_field="sparse_embedding",
                param={"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
                limit=top_k * 2,
                expr=filter_expr,
            )

            client = self._get_client()
            results = client.hybrid_search(
                collection_name=config.MILVUS_COLLECTION,
                reqs=[dense_search, sparse_search],
                ranker=RRFRanker(k=rrf_k),
                limit=top_k,
                output_fields=output_fields,
            )

            formatted_results: list[Document] = []
            for hits in results:
                for hit in hits:
                    entity = hit.get("entity", {}) or {}
                    metadata = {
                        "id": hit.get("id"),
                        "filename": entity.get("filename", ""),
                        "file_type": entity.get("file_type", ""),
                        "file_path": entity.get("file_path", ""),
                        "page_number": entity.get("page_number", 0),
                        "chunk_id": entity.get("chunk_id", ""),
                        "parent_chunk_id": entity.get("parent_chunk_id", ""),
                        "root_chunk_id": entity.get("root_chunk_id", ""),
                        "chunk_level": entity.get("chunk_level", 0),
                        "chunk_idx": entity.get("chunk_idx", 0),
                        "_source": entity.get("_source", ""),
                        "_extension": entity.get("_extension", ""),
                        "_file_name": entity.get("_file_name", ""),
                        "h1": entity.get("h1", ""),
                        "h2": entity.get("h2", ""),
                        "h3": entity.get("h3", ""),
                        "start_index": entity.get("start_index", 0),
                        "score": hit.get("distance", 0.0),
                    }
                    formatted_results.append(
                        Document(page_content=entity.get("text", ""), metadata=metadata)
                    )

            logger.info("Milvus 混合检索完成，返回 {} 条文档", len(formatted_results))
            return formatted_results
        except Exception as exc:
            logger.error("Milvus 混合检索失败: {}", exc)
            raise

    def dense_retrieve(
        self,
        dense_embedding: list[float],
        top_k: int = 5,
        filter_expr: str = "",
    ) -> list[Document]:
        try:
            client = self._get_client()
            results = client.search(
                collection_name=config.MILVUS_COLLECTION,
                data=[dense_embedding],
                anns_field="dense_embedding",
                search_params={"metric_type": "IP", "params": {"ef": 64}},
                limit=top_k,
                output_fields=[
                    "text",
                    "filename",
                    "file_type",
                    "file_path",
                    "page_number",
                    "chunk_id",
                    "parent_chunk_id",
                    "root_chunk_id",
                    "chunk_level",
                    "chunk_idx",
                    "_source",
                    "_extension",
                    "_file_name",
                    "h1",
                    "h2",
                    "h3",
                    "start_index",
                ],
                filter=filter_expr,
            )

            formatted_results: list[Document] = []
            for hits in results:
                for hit in hits:
                    entity = hit.get("entity", {}) or {}
                    metadata = {
                        "id": hit.get("id"),
                        "filename": entity.get("filename", ""),
                        "file_type": entity.get("file_type", ""),
                        "file_path": entity.get("file_path", ""),
                        "page_number": entity.get("page_number", 0),
                        "chunk_id": entity.get("chunk_id", ""),
                        "parent_chunk_id": entity.get("parent_chunk_id", ""),
                        "root_chunk_id": entity.get("root_chunk_id", ""),
                        "chunk_level": entity.get("chunk_level", 0),
                        "chunk_idx": entity.get("chunk_idx", 0),
                        "_source": entity.get("_source", ""),
                        "_extension": entity.get("_extension", ""),
                        "_file_name": entity.get("_file_name", ""),
                        "h1": entity.get("h1", ""),
                        "h2": entity.get("h2", ""),
                        "h3": entity.get("h3", ""),
                        "start_index": entity.get("start_index", 0),
                        "score": hit.get("distance", 0.0),
                    }
                    formatted_results.append(
                        Document(page_content=entity.get("text", ""), metadata=metadata)
                    )

            logger.info("Milvus 稠密检索完成，返回 {} 条文档", len(formatted_results))
            return formatted_results
        except Exception as exc:
            logger.error("Milvus 稠密检索失败: {}", exc)
            raise

    def delete(self, filter_expr: str):
        try:
            client = self._get_client()
            result = client.delete(
                collection_name=config.MILVUS_COLLECTION,
                filter=filter_expr,
            )
            logger.info("Milvus 删除完成，过滤条件: {}", filter_expr)
            return result
        except Exception as exc:
            logger.error("Milvus 删除失败: {}", exc)
            raise

    def has_collection(self) -> bool:
        try:
            client = self._get_client()
            result = client.has_collection(config.MILVUS_COLLECTION)
            logger.info("Milvus 集合存在性检查完成，结果: {}", result)
            return result
        except Exception as exc:
            logger.error("Milvus 集合存在性检查失败: {}", exc)
            raise

    def health_check(self) -> bool:
        try:
            client = self._get_client()
            client.list_collections()
            logger.info("Milvus 健康检查完成，连接正常")
            return True
        except Exception as exc:
            logger.error("Milvus 健康检查失败: {}", exc)
            return False

    def drop_collection(self):
        try:
            client = self._get_client()
            if client.has_collection(config.MILVUS_COLLECTION):
                client.drop_collection(config.MILVUS_COLLECTION)
                logger.info("Milvus 集合删除完成: {}", config.MILVUS_COLLECTION)
            else:
                logger.info("Milvus 集合不存在，无需删除: {}", config.MILVUS_COLLECTION)
        except Exception as exc:
            logger.error("Milvus 集合删除失败: {}", exc)
            raise

    def close(self) -> None:
        try:
            self.client = None
            logger.info("Milvus 连接已关闭")
        except Exception as exc:
            logger.error("Milvus 连接关闭失败: {}", exc)
            raise


mlivus_client_service = MilvusManager()
