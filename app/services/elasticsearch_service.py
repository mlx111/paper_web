from __future__ import annotations

import logging
from typing import Any

from elasticsearch import Elasticsearch
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)


class ElasticsearchService:
    """Elasticsearch 仓储单例。"""

    def __init__(
        self,
        host: str = "http://localhost:9200",
        username: str = "elastic",
        password: str = "scngjmdEejUthfxi*heY",
    ) -> None:
        self.es = Elasticsearch(
            host,
            basic_auth=(username, password),
            verify_certs=False,
        )
        logger.info("Elasticsearch 仓储初始化完成")

    def query(self, search: str) -> Any:
        if not search:
            logger.error("\u6267\u884c Elasticsearch \u67e5\u8be2\u5931\u8d25\uff1a\u641c\u7d22\u8bcd\u4e0d\u80fd\u4e3a\u7a7a")
            raise HTTPException(status_code=400, detail="Search query is required")

        body = {
            "query": {
                "match": {
                    "content": search,
                }
            }
        }
        try:
            result = self.es.search(index="my_index", body=body)
            logger.info("\u6267\u884c Elasticsearch \u67e5\u8be2\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u6267\u884c Elasticsearch \u67e5\u8be2\u5931\u8d25: %s", exc)
            raise

    def upload(self, file: UploadFile) -> None:
        logger.info("\u6587\u4ef6\u4e0a\u4f20\u63a5\u53e3\u8c03\u7528\u5b8c\u6210\uff0c\u5f53\u524d\u672a\u5b9e\u73b0\u5177\u4f53\u903b\u8f91")
        return None

    def create_index(self, index: str) -> Any:
        mappings = {
            "properties": {
                "foo": {"type": "text"},
                "bar": {
                    "type": "text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "ignore_above": 256,
                        }
                    },
                },
            }
        }
        try:
            result = self.es.indices.create(index=index, mappings=mappings)
            logger.info("\u521b\u5efa Elasticsearch \u7d22\u5f15\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u521b\u5efa Elasticsearch \u7d22\u5f15\u5931\u8d25: %s", exc)
            raise

    def index_docment(self, index: str, id: str) -> Any:
        doc = {
            "foo": "This is a test document.",
            "bar": "This is another field.",
        }
        try:
            result = self.es.index(index=index, id=id, document=doc)
            logger.info("\u5199\u5165 Elasticsearch \u6587\u6863\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u5199\u5165 Elasticsearch \u6587\u6863\u5931\u8d25: %s", exc)
            raise

    def update_docment(self, index: str, id: str) -> Any:
        doc = {
            "foo": "This is an updated test document.",
            "bar": "This is another updated field.",
        }
        try:
            result = self.es.update(index=index, id=id, doc=doc)
            logger.info("\u66f4\u65b0 Elasticsearch \u6587\u6863\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u66f4\u65b0 Elasticsearch \u6587\u6863\u5931\u8d25: %s", exc)
            raise

    def delete_docment(self, index: str, id: str) -> Any:
        try:
            result = self.es.delete(index=index, id=id)
            logger.info("\u5220\u9664 Elasticsearch \u6587\u6863\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u5220\u9664 Elasticsearch \u6587\u6863\u5931\u8d25: %s", exc)
            raise

    def delete_index(self, index: str) -> Any:
        try:
            result = self.es.indices.delete(index=index)
            logger.info("\u5220\u9664 Elasticsearch \u7d22\u5f15\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u5220\u9664 Elasticsearch \u7d22\u5f15\u5931\u8d25: %s", exc)
            raise

    def get_docment(self, index: str, id: str) -> Any:
        try:
            result = self.es.get(index=index, id=id)
            logger.info("\u83b7\u53d6 Elasticsearch \u6587\u6863\u5b8c\u6210")
            return result
        except Exception as exc:
            logger.error("\u83b7\u53d6 Elasticsearch \u6587\u6863\u5931\u8d25: %s", exc)
            raise


elasticsearch_repo = ElasticsearchService()


def query(search: str) -> Any:
    return elasticsearch_repo.query(search)


def upload(file: UploadFile) -> None:
    return elasticsearch_repo.upload(file)


def create_index(index: str) -> Any:
    return elasticsearch_repo.create_index(index)


def index_docment(index: str, id: str) -> Any:
    return elasticsearch_repo.index_docment(index, id)


def update_docment(index: str, id: str) -> Any:
    return elasticsearch_repo.update_docment(index, id)


def delete_docment(index: str, id: str) -> Any:
    return elasticsearch_repo.delete_docment(index, id)


def delete_index(index: str) -> Any:
    return elasticsearch_repo.delete_index(index)


def get_docment(index: str, id: str) -> Any:
    return elasticsearch_repo.get_docment(index, id)
