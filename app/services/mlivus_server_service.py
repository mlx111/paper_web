from langchain_core.documents import Document
from loguru import logger

from services.embodeding_service import Embodedings
from services.chunk_image_store_service import strip_image_placeholders
from services.mlivus_client_service import MilvusManager


class MlivusServerService:
    def __init__(
        self,
        embeddings: Embodedings = None,
        milvusmanger: MilvusManager = None,
    ) -> None:
        self.embedding_service = embeddings or Embodedings()
        self.milvus_manager = milvusmanger or MilvusManager()

    def write_documents(self, documents: list[Document], batch_size: int = 10):
        if not documents:
            return

        import time

        self.milvus_manager.init_collection()
        start_time = time.time()
        all_texts = [strip_image_placeholders(doc.page_content) or doc.page_content for doc in documents]
        self.embedding_service.fit_corpus(all_texts)

        total = len(documents)
        for i in range(0, total, batch_size):
            batch = documents[i:i + batch_size]
            texts = [strip_image_placeholders(doc.page_content) or doc.page_content for doc in batch]
            dense_embeddings, sparse_embeddings = self.embedding_service.get_all_embeddings(texts)

            insert_data = [
                {
                    "dense_embedding": dense_emb,
                    "sparse_embedding": sparse_emb,
                    "text": doc.page_content,
                    "filename": doc.metadata.get("filename", ""),
                    "file_type": doc.metadata.get("file_type", ""),
                    "file_path": doc.metadata.get("file_path", ""),
                    "page_number": doc.metadata.get("page_number", 0),
                    "chunk_idx": doc.metadata.get("chunk_idx", 0),
                    "chunk_id": doc.metadata.get("chunk_id", ""),
                    "parent_chunk_id": doc.metadata.get("parent_chunk_id", ""),
                    "root_chunk_id": doc.metadata.get("root_chunk_id", ""),
                    "chunk_level": doc.metadata.get("chunk_level", 0),
                    "_source": doc.metadata.get("_source", ""),
                    "_extension": doc.metadata.get("_extension", ""),
                    "_file_name": doc.metadata.get("_file_name", ""),
                    "h1": doc.metadata.get("h1", ""),
                    "h2": doc.metadata.get("h2", ""),
                    "h3": doc.metadata.get("h3", ""),
                    "start_index": int(doc.metadata.get("start_index", 0) or 0),
                }
                for doc, dense_emb, sparse_emb in zip(batch, dense_embeddings, sparse_embeddings)
            ]
            self.milvus_manager.insert(insert_data)

        elapsed = time.time() - start_time
        logger.info(
            "批量添加 {} 个文档到 VectorStore 完成, 耗时: {:.2f}s, 平均: {:.2f}s/个",
            len(documents),
            elapsed,
            elapsed / len(documents),
        )

    def delete_by_source(self, file_path: str) -> int:
        """Delete all indexed chunks that come from the given source path."""
        if not file_path:
            return 0

        try:
            self.milvus_manager.init_collection()
            escaped_path = file_path.replace("\\", "\\\\").replace('"', '\\"')
            expr = f'_source == "{escaped_path}"'
            result = self.milvus_manager.delete(expr)
            deleted_count = result.delete_count if hasattr(result, "delete_count") else 0
            logger.info("删除文件旧数据 {}，删除数量: {}", file_path, deleted_count)
            return deleted_count
        except Exception as exc:
            logger.warning("删除旧数据失败 {}: {}", file_path, exc)
            return 0


mlivus_server_service = MlivusServerService()
