import json
from pathlib import Path
from typing import Dict, List

from langchain_core.documents import Document
from loguru import logger


class ParentChunkStore:
    """Local JSON-based parent chunk storage."""

    def __init__(self, store_path: Path | None = None):
        base_dir = Path(__file__).resolve().parent
        self.store_path = store_path or (base_dir.parent / "data" / "parent_chunks.json")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("父块存储服务初始化完成")

    def _load(self) -> Dict[str, dict]:
        try:
            if not self.store_path.exists():
                logger.info("父块存储读取完成，文件不存在，返回空数据")
                return {}
            with open(self.store_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            result = data if isinstance(data, dict) else {}
            logger.info("父块存储读取完成，记录数: {}", len(result))
            return result
        except Exception as exc:
            logger.error("父块存储读取失败: {}", exc)
            return {}

    def _save(self, data: Dict[str, dict]) -> None:
        try:
            tmp_path = self.store_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False)
            tmp_path.replace(self.store_path)
            logger.info("父块存储写入完成，记录数: {}", len(data))
        except Exception as exc:
            logger.error("父块存储写入失败: {}", exc)
            raise

    def upsert_documents(self, docs: List[Document]) -> int:
        try:
            if not docs:
                logger.info("父块写入完成，输入为空")
                return 0

            store = self._load()
            upserted = 0
            for doc in docs:
                metadata = doc.metadata or {}
                chunk_id = str(metadata.get("chunk_id", "")).strip()
                if not chunk_id:
                    continue

                store[chunk_id] = {
                    "text": doc.page_content or "",
                    "filename": metadata.get("filename", ""),
                    "file_type": metadata.get("file_type", ""),
                    "file_path": metadata.get("file_path", ""),
                    "page_number": metadata.get("page_number", 0),
                    "chunk_id": chunk_id,
                    "parent_chunk_id": metadata.get("parent_chunk_id", ""),
                    "root_chunk_id": metadata.get("root_chunk_id", ""),
                    "chunk_level": int(metadata.get("chunk_level", 0) or 0),
                    "chunk_idx": int(metadata.get("chunk_idx", 0) or 0),
                    "_source": metadata.get("_source", ""),
                    "_extension": metadata.get("_extension", ""),
                    "_file_name": metadata.get("_file_name", ""),
                    "h1": metadata.get("h1", ""),
                    "h2": metadata.get("h2", ""),
                    "h3": metadata.get("h3", ""),
                    "start_index": int(metadata.get("start_index", 0) or 0),
                }
                upserted += 1

            self._save(store)
            logger.info("父块写入完成，写入 {} 条记录", upserted)
            return upserted
        except Exception as exc:
            logger.error("父块写入失败: {}", exc)
            raise

    def get_documents_by_ids(self, chunk_ids: List[str]) -> List[dict]:
        try:
            if not chunk_ids:
                logger.info("按 ID 获取父块完成，输入为空")
                return []

            store = self._load()
            result = [store[item] for item in chunk_ids if item in store]
            logger.info("按 ID 获取父块完成，命中 {} 条", len(result))
            return result
        except Exception as exc:
            logger.error("按 ID 获取父块失败: {}", exc)
            raise

    def get_langchain_documents_by_ids(self, chunk_ids: List[str]) -> List[Document]:
        try:
            raw_docs = self.get_documents_by_ids(chunk_ids)
            documents: List[Document] = []

            for item in raw_docs:
                metadata = {
                    "filename": item.get("filename", ""),
                    "file_type": item.get("file_type", ""),
                    "file_path": item.get("file_path", ""),
                    "page_number": item.get("page_number", 0),
                    "chunk_id": item.get("chunk_id", ""),
                    "parent_chunk_id": item.get("parent_chunk_id", ""),
                    "root_chunk_id": item.get("root_chunk_id", ""),
                    "chunk_level": item.get("chunk_level", 0),
                    "chunk_idx": item.get("chunk_idx", 0),
                    "_source": item.get("_source", ""),
                    "_extension": item.get("_extension", ""),
                    "_file_name": item.get("_file_name", ""),
                    "h1": item.get("h1", ""),
                    "h2": item.get("h2", ""),
                    "h3": item.get("h3", ""),
                    "start_index": item.get("start_index", 0),
                }
                documents.append(Document(page_content=item.get("text", ""), metadata=metadata))

            logger.info("LangChain 父块转换完成，文档数: {}", len(documents))
            return documents
        except Exception as exc:
            logger.error("LangChain 父块转换失败: {}", exc)
            raise

    def delete_by_filename(self, filename: str) -> int:
        try:
            if not filename:
                logger.info("按文件名删除父块完成，输入为空")
                return 0

            store = self._load()
            before = len(store)
            filtered = {key: value for key, value in store.items() if value.get("filename") != filename}
            deleted = before - len(filtered)
            if deleted > 0:
                self._save(filtered)
            logger.info("按文件名删除父块完成，删除 {} 条", deleted)
            return deleted
        except Exception as exc:
            logger.error("按文件名删除父块失败: {}", exc)
            raise

    def delete_by_source(self, file_path: str) -> int:
        try:
            if not file_path:
                logger.info("按来源删除父块完成，输入为空")
                return 0

            store = self._load()
            before = len(store)
            filtered = {key: value for key, value in store.items() if value.get("_source") != file_path}
            deleted = before - len(filtered)
            if deleted > 0:
                self._save(filtered)
            logger.info("按来源删除父块完成，删除 {} 条", deleted)
            return deleted
        except Exception as exc:
            logger.error("按来源删除父块失败: {}", exc)
            raise


parent_chunk_store = ParentChunkStore()
