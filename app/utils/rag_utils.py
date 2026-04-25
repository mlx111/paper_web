from collections import defaultdict
from textwrap import dedent
from typing import Any, Dict, List, Tuple
import json
import os

import requests
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from loguru import logger

from context.context_config import ContextConfig
from services.embodeding_service import Embodedings
from services.mlivus_client_service import MilvusManager
from services.parent_chunk_service import ParentChunkStore
from context.builder import ContextBuilder
from utils.history import get_history

load_dotenv()


class RagUtilsService:
    def __init__(
        self,
        embeddings: Embodedings = None,
        milvus_manager: MilvusManager = None,
        parent_chunk_store: ParentChunkStore = None,
    ) -> None:
        self.embedding_service = embeddings or Embodedings()
        self.milvus_manager = milvus_manager or MilvusManager()
        self.parent_chunk_store = parent_chunk_store or ParentChunkStore()

        self.ark_api_key = os.getenv("ARK_API_KEY")
        self.model = os.getenv("MODEL")
        self.base_url = os.getenv("BASE_URL")
        self.rerank_model = os.getenv("RERANK_MODEL")
        self.rerank_endpoint = (
            os.getenv("RERANK_ENDPOINT")
            or os.getenv("RERANK_BINDING_HOST")
            or "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        )
        self.rerank_api_key = os.getenv("RERANK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.auto_merge_enabled = os.getenv("AUTO_MERGE_ENABLED", "true").lower() != "false"
        self.auto_merge_threshold = int(os.getenv("AUTO_MERGE_THRESHOLD", "2"))
        self.leaf_retrieve_level = int(os.getenv("LEAF_RETRIEVE_LEVEL", "3"))

        self._stepback_model = None
        # ContextBuilder turns retrieval output into a prompt-ready bundle.
        # We keep it here so router / agents can request structured context
        # without duplicating gather / select / assemble logic.
        self.context_builder = ContextBuilder(
            history_loader=get_history,
            knowledge_retriever=self._retrieve_context_documents,
            parent_chunk_retriever=None,
            rerank_fn=None,
            config=ContextConfig(
                max_tokens=3000,
                reserve_ratio=0.2,
                min_relevance=0.1,
                enable_compression=True,
                recency_weight=0.3,
                relevance_weight=0.7,
                max_history_messages=12,
                max_history_turns=6,
                max_evidence_items=6,
                max_note_items=4,
                max_chars=12000,
            ),
        )

    def _retrieve_context_documents(self, query: str, top_k: int):
        """Lightweight adapter used by ContextBuilder.

        The builder only needs a list of documents to convert into evidence.
        We reuse the existing retrieval pipeline so the new context layer stays
        compatible with the current RAG implementation.
        """
        retrieved = self.retrieve_documents(query=query, top_k=top_k)
        return retrieved.get("docs", [])

    def build_context_bundle(
        self,
        query: str,
        session_id: str,
        mode: str = "deep",
        top_k: int = 8,
        evidence_top_k: int = 6,
    ):
        """Build a structured context bundle for router / agents.

        This is the main entry point for the new context-engineering layer.
        It keeps retrieval concerns inside RagUtils while giving callers a single
        prompt-ready object.
        """
        return self.context_builder.build(
            question=query,
            session_id=session_id,
            mode=mode,
            top_k=top_k,
            evidence_top_k=evidence_top_k,
        )

    def _get_rerank_endpoint(self) -> str:
        if not self.rerank_endpoint:
            return ""
        return self.rerank_endpoint.strip().rstrip("/")

    def _doc_score(self, doc: Document) -> float:
        metadata = doc.metadata or {}
        score = metadata.get("rerank_score", metadata.get("score", 0.0))
        try:
            return float(score)
        except (TypeError, ValueError):
            return 0.0

    def _doc_identity(self, doc: Document) -> Any:
        metadata = doc.metadata or {}
        return metadata.get("chunk_id") or (
            metadata.get("filename"),
            metadata.get("page_number"),
            doc.page_content,
        )

    def _merge_to_parent_level(
        self, docs: List[Document], threshold: int = 2
    ) -> Tuple[List[Document], int]:
        groups: Dict[str, List[Document]] = defaultdict(list)
        for doc in docs:
            metadata = doc.metadata or {}
            parent_id = str(metadata.get("parent_chunk_id", "")).strip()
            if parent_id:
                groups[parent_id].append(doc)

        merge_parent_ids = [
            parent_id for parent_id, children in groups.items() if len(children) >= threshold
        ]
        if not merge_parent_ids:
            return docs, 0

        parent_docs = self.parent_chunk_store.get_langchain_documents_by_ids(merge_parent_ids)
        parent_map = {
            str((parent_doc.metadata or {}).get("chunk_id", "")).strip(): parent_doc
            for parent_doc in parent_docs
            if str((parent_doc.metadata or {}).get("chunk_id", "")).strip()
        }

        merged_by_parent: Dict[str, Document] = {}
        merged_docs: List[Document] = []
        merged_count = 0

        for doc in docs:
            metadata = doc.metadata or {}
            parent_id = str(metadata.get("parent_chunk_id", "")).strip()
            if not parent_id or parent_id not in parent_map:
                merged_docs.append(doc)
                continue

            if parent_id not in merged_by_parent:
                parent_doc = parent_map[parent_id]
                parent_metadata = dict(parent_doc.metadata or {})
                child_scores = [self._doc_score(child) for child in groups[parent_id]]
                parent_metadata["score"] = (
                    max(child_scores) if child_scores else self._doc_score(parent_doc)
                )
                parent_metadata["merged_from_children"] = True
                parent_metadata["merged_child_count"] = len(groups[parent_id])
                merged_by_parent[parent_id] = Document(
                    page_content=parent_doc.page_content,
                    metadata=parent_metadata,
                )
                merged_docs.append(merged_by_parent[parent_id])

            merged_count += 1

        deduped: List[Document] = []
        seen = set()
        for item in merged_docs:
            key = self._doc_identity(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        return deduped, merged_count

    def _auto_merge_documents(
        self, docs: List[Document], top_k: int
    ) -> Tuple[List[Document], Dict[str, Any]]:
        if not self.auto_merge_enabled or not docs:
            return docs[:top_k], {
                "auto_merge_enabled": self.auto_merge_enabled,
                "auto_merge_applied": False,
                "auto_merge_threshold": self.auto_merge_threshold,
                "auto_merge_replaced_chunks": 0,
                "auto_merge_steps": 0,
            }

        merged_docs, merged_count_l3_l2 = self._merge_to_parent_level(
            docs, threshold=self.auto_merge_threshold
        )
        merged_docs, merged_count_l2_l1 = self._merge_to_parent_level(
            merged_docs, threshold=self.auto_merge_threshold
        )

        merged_docs.sort(key=self._doc_score, reverse=True)
        merged_docs = merged_docs[:top_k]

        replaced_count = merged_count_l3_l2 + merged_count_l2_l1
        return merged_docs, {
            "auto_merge_enabled": self.auto_merge_enabled,
            "auto_merge_applied": replaced_count > 0,
            "auto_merge_threshold": self.auto_merge_threshold,
            "auto_merge_replaced_chunks": replaced_count,
            "auto_merge_steps": int(merged_count_l3_l2 > 0) + int(merged_count_l2_l1 > 0),
        }

    def _rerank_documents(
        self, query: str, docs: List[Document], top_k: int
    ) -> Tuple[List[Document], Dict[str, Any]]:
        meta: Dict[str, Any] = {
            "rerank_enabled": bool(
                self.rerank_model and self.rerank_api_key and self.rerank_endpoint
            ),
            "rerank_applied": False,
            "rerank_model": self.rerank_model,
            "rerank_endpoint": self._get_rerank_endpoint(),
            "rerank_error": None,
            "candidate_count": len(docs),
        }
        if not docs or not meta["rerank_enabled"]:
            return docs[:top_k], meta

        payload = {
            "model": self.rerank_model,
            "input": {
                "query": query,
                "documents": [doc.page_content or "" for doc in docs],
            },
            "parameters": {
                "top_n": min(top_k, len(docs)),
                "return_documents": False,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.rerank_api_key}",
        }
        try:
            response = requests.post(
                meta["rerank_endpoint"],
                headers=headers,
                json=payload,
                timeout=15,
            )
            if response.status_code >= 400:
                meta["rerank_error"] = f"HTTP {response.status_code}: {response.text}"
                logger.error("rerank request failed: {}", meta["rerank_error"])
                return docs[:top_k], meta

            items = response.json().get("output", {}).get("results", [])
            reranked: List[Document] = []
            for item in items:
                idx = item.get("index")
                if not isinstance(idx, int) or not (0 <= idx < len(docs)):
                    continue

                source_doc = docs[idx]
                metadata = dict(source_doc.metadata or {})
                metadata["rrf_rank"] = idx + 1

                score = item.get("relevance_score")
                if score is not None:
                    metadata["rerank_score"] = score

                reranked.append(
                    Document(
                        page_content=source_doc.page_content,
                        metadata=metadata,
                    )
                )

            if reranked:
                meta["rerank_applied"] = True
                logger.info("rerank finished, kept {} docs", len(reranked))
                return reranked[:top_k], meta

            meta["rerank_error"] = "empty_rerank_results"
            logger.warning("rerank returned empty results")
            return docs[:top_k], meta
        except (
            requests.RequestException,
            json.JSONDecodeError,
            KeyError,
            ValueError,
            TypeError,
        ) as exc:
            meta["rerank_error"] = str(exc)
            logger.error("rerank raised exception: {}", exc)
            return docs[:top_k], meta

    def _get_stepback_model(self):
        if not self.ark_api_key or not self.model:
            return None
        if self._stepback_model is None:
            self._stepback_model = init_chat_model(
                model=self.model,
                model_provider="openai",
                api_key=self.ark_api_key,
                base_url=self.base_url,
                temperature=0.2,
            )
        return self._stepback_model

    def generate_step_back_question(self, query: str) -> str:
        model = self._get_stepback_model()
        if not model:
            return ""
        prompt = (
           "请将用户的具体问题抽象成更高层次、更概括的“退一步问题”，"
        "用于探索背后的通用原理或核心概念。只输出退一步问题一句话，不要解释。\n"
        f"用户问题：{query}"
        )
        try:
            return (model.invoke(prompt).content or "").strip()
        except Exception:
            return ""

    def answer_step_back_question(self, step_back_question: str) -> str:
        model = self._get_stepback_model()
        if not model or not step_back_question:
            return ""
        prompt = (
            "请简要回答以下退一步问题，提供通用原理/背景知识，"
        "控制在20字以内。只输出答案，不要列出推理过程。\n"
        f"退一步问题：{step_back_question}"
        )
        try:
            return (model.invoke(prompt).content or "").strip()
        except Exception:
            return ""

    def generate_hypothetical_document(self, query: str) -> str:
        model = self._get_stepback_model()
        if not model:
            return ""
        prompt = dedent(
           "请基于用户问题生成一段“假设性文档”，内容应像真实资料片段，"
        "用于帮助检索相关信息。文档可以包含合理推测，但需与问题语义相关。"
        "只输出文档正文，不要标题或解释。\n"
        f"用户问题：{query}"
        )
        try:
            return (model.invoke(prompt).content or "").strip()
        except Exception:
            return ""

    def step_back_expand(self, query: str) -> Dict[str, str]:
        step_back_question = self.generate_step_back_question(query)
        step_back_answer = self.answer_step_back_question(step_back_question)
        if step_back_question or step_back_answer:
            expanded_query = (
                f"{query}\n\n"
                f"閫€涓€姝ラ棶棰橈細{step_back_question}\n"
                f"閫€涓€姝ョ瓟妗堬細{step_back_answer}"
            )
        else:
            expanded_query = query

        return {
            "step_back_question": step_back_question,
            "step_back_answer": step_back_answer,
            "expanded_query": expanded_query,
        }

    def retrieve_documents(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        candidate_k = max(top_k * 3, top_k)
        filter_expr = f"chunk_level == {self.leaf_retrieve_level}"
        try:
            dense_embeddings = self.embedding_service.get_emboddings([query])
            dense_embedding = dense_embeddings[0]
            sparse_embedding = self.embedding_service.get_sparse_embedding(query)

            retrieved = self.milvus_manager.hybrid_retrieve(
                dense_embedding=dense_embedding,
                sparse_embedding=sparse_embedding,
                top_k=candidate_k,
                filter_expr=filter_expr,
            )
            reranked, rerank_meta = self._rerank_documents(
                query=query, docs=retrieved, top_k=top_k
            )
            merged_docs, merge_meta = self._auto_merge_documents(
                docs=reranked, top_k=top_k
            )
            rerank_meta["retrieval_mode"] = "hybrid"
            rerank_meta["candidate_k"] = candidate_k
            rerank_meta["leaf_retrieve_level"] = self.leaf_retrieve_level
            rerank_meta.update(merge_meta)
            return {"docs": merged_docs, "meta": rerank_meta}
        except Exception as exc:
            logger.warning("hybrid retrieve failed, fallback to dense: {}", exc)
            try:
                dense_embeddings = self.embedding_service.get_emboddings([query])
                dense_embedding = dense_embeddings[0]
                retrieved = self.milvus_manager.dense_retrieve(
                    dense_embedding=dense_embedding,
                    top_k=candidate_k,
                    filter_expr=filter_expr,
                )
                reranked, rerank_meta = self._rerank_documents(
                    query=query, docs=retrieved, top_k=top_k
                )
                merged_docs, merge_meta = self._auto_merge_documents(
                    docs=reranked, top_k=top_k
                )
                rerank_meta["retrieval_mode"] = "dense_fallback"
                rerank_meta["candidate_k"] = candidate_k
                rerank_meta["leaf_retrieve_level"] = self.leaf_retrieve_level
                rerank_meta.update(merge_meta)
                return {"docs": merged_docs, "meta": rerank_meta}
            except Exception as fallback_exc:
                logger.error("retrieve_documents failed: {}", fallback_exc)
                return {
                    "docs": [],
                    "meta": {
                        "rerank_enabled": bool(
                            self.rerank_model
                            and self.rerank_api_key
                            and self.rerank_endpoint
                        ),
                        "rerank_applied": False,
                        "rerank_model": self.rerank_model,
                        "rerank_endpoint": self._get_rerank_endpoint(),
                        "rerank_error": "retrieve_failed",
                        "retrieval_mode": "failed",
                        "candidate_k": candidate_k,
                        "leaf_retrieve_level": self.leaf_retrieve_level,
                        "auto_merge_enabled": self.auto_merge_enabled,
                        "auto_merge_applied": False,
                        "auto_merge_threshold": self.auto_merge_threshold,
                        "auto_merge_replaced_chunks": 0,
                        "auto_merge_steps": 0,
                        "candidate_count": 0,
                    },
                }


rag_utils_service = RagUtilsService()


def generate_step_back_question(query: str) -> str:
    return rag_utils_service.generate_step_back_question(query)


def answer_step_back_question(step_back_question: str) -> str:
    return rag_utils_service.answer_step_back_question(step_back_question)


def generate_hypothetical_document(query: str) -> str:
    return rag_utils_service.generate_hypothetical_document(query)


def step_back_expand(query: str) -> Dict[str, str]:
    return rag_utils_service.step_back_expand(query)


def retrieve_documents(query: str, top_k: int = 5) -> Dict[str, Any]:
    return rag_utils_service.retrieve_documents(query=query, top_k=top_k)

