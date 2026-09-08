from __future__ import annotations

from typing import Any, Callable, Iterable

from .context_config import ContextConfig
from context.types import ContextCandidate


class ContextGatherer:
    """
    Gather 阶段。

    这个阶段只负责收集原料：
    - 历史消息
    - 知识库检索结果
    - 父块检索结果
    - 结构化笔记（旧系统）
    - 结构化记忆（新系统，语义筛选）

    不做筛选，不做压缩，不做最终拼装。
    """

    def __init__(
        self,
        history_loader: Callable[[str], Any],
        knowledge_retriever: Callable[[str, int], Iterable[Any]] | None = None,
        parent_chunk_retriever: Callable[[str, int], Iterable[Any]] | None = None,
        notes_loader: Callable[[str], Any] | None = None,
        memory_loader: Callable[[str, int], list[dict[str, Any]]] | None = None,
        config: ContextConfig | None = None,
    ):
        self.history_loader = history_loader
        self.knowledge_retriever = knowledge_retriever
        self.parent_chunk_retriever = parent_chunk_retriever
        self.notes_loader = notes_loader
        self.memory_loader = memory_loader
        self.config = config or ContextConfig()
        self.max_history_messages = self.config.max_history_messages
        self.max_note_items = self.config.max_note_items
        self.max_memory_items = self.config.max_memory_items


    def _load_history(self, session_id: str) -> list[dict[str, Any]]:
        """
        从历史存储里读取会话历史。

        这里兼容两种情况：
        1. 返回的是带 .messages 的 HistoryService / BaseChatMessageHistory
        2. 直接返回 list
        """
        history_obj = self.history_loader(session_id)

        if isinstance(history_obj, list):
            raw_messages = history_obj
        else:
            raw_messages = getattr(history_obj, "messages", []) or []

        normalized: list[dict[str, Any]] = []
        for msg in raw_messages[-self.max_history_messages:]:
            role = "assistant"
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)

            if msg_type in ("human", "user"):
                role = "user"
            elif msg_type in ("ai", "assistant"):
                role = "assistant"

            content = self._to_text(msg)
            if content:
                normalized.append(
                    {
                        "role": role,
                        "content": content,
                        "metadata": self._to_metadata(msg),
                    }
                )

        return normalized
    def _load_notes(self, session_id: str) -> list[dict[str, Any]]:
        """
        读取结构化笔记（旧系统）。

        这里兼容两种情况：
        1. 返回的是 NoteService
        2. 直接返回 list
        """
        if self.notes_loader is None:
            return []

        notes_obj = self.notes_loader(session_id)

        if isinstance(notes_obj, list):
            raw_notes = notes_obj
        else:
            raw_notes = getattr(notes_obj, "list_notes", None)
            if callable(raw_notes):
                raw_notes = raw_notes()
            else:
                raw_notes = getattr(notes_obj, "notes", []) or []

        normalized: list[dict[str, Any]] = []
        for note in (raw_notes or [])[: self.max_note_items]:
            if not isinstance(note, dict):
                continue

            title = str(note.get("title", "")).strip()
            content = str(note.get("content", "")).strip()
            if not content and not title:
                continue

            normalized.append(
                {
                    "title": title,
                    "content": content,
                    "tags": note.get("tags", []),
                    "kind": note.get("kind", "note"),
                    "importance": note.get("importance", 0.5),
                    "metadata": note.get("extra", {}) or {},
                }
            )

        return normalized

    def _load_memories(
        self, question: str, session_id: str
    ) -> list[dict[str, Any]]:
        """
        从新的结构化记忆系统中按语义筛选加载记忆。

        与 _load_notes 不同：
        - notes 全量加载，按 importance 排序取 top N
        - memories 先做语义筛选（最多 5 条），再加载
        """
        if self.memory_loader is None:
            return []

        try:
            memories = self.memory_loader(question, self.max_memory_items)
            if not memories:
                return []

            normalized: list[dict[str, Any]] = []
            for mem in (memories or []):
                if not isinstance(mem, dict):
                    continue

                title = str(mem.get("title", "")).strip()
                content = str(mem.get("content", "")).strip()
                if not content and not title:
                    continue

                normalized.append(
                    {
                        "title": title,
                        "content": content,
                        "tags": mem.get("tags", []),
                        "kind": f"memory:{mem.get('kind', 'project')}",
                        "importance": mem.get("importance", 0.9),
                        "metadata": mem.get("metadata", {}) or {},
                    }
                )

            return normalized
        except Exception:
            return []

    def _to_text(self, item: Any) -> str:
        """尽量把各种对象转成文本。"""
        if item is None:
            return ""

        if isinstance(item, str):
            return item.strip()

        if isinstance(item, dict):
            for key in ("content", "text", "page_content", "chunk", "message"):
                value = item.get(key)
                if value:
                    return str(value).strip()
            return str(item).strip()

        for attr in ("content", "text", "page_content"):
            value = getattr(item, attr, None)
            if value:
                return str(value).strip()

        return str(item).strip()

    def _to_metadata(self, item: Any) -> dict[str, Any]:
        """提取候选项附带的 metadata。"""
        if isinstance(item, dict):
            metadata = item.get("metadata")
            return dict(metadata) if isinstance(metadata, dict) else {}

        metadata = getattr(item, "metadata", None)
        return dict(metadata) if isinstance(metadata, dict) else {}

    def _extract_score(self, item: Any, metadata: dict[str, Any]) -> float:
        """
        从检索结果里提取一个可用于排序的分数。

        这里按优先级依次尝试：
        1. metadata 里的 rerank_score
        2. metadata 里的 relevance_score
        3. metadata 里的 score
        4. 如果有 rrf_rank，就根据名次反推一个分数
        5. 实在没有，就退回 item.score 或 0.0
        """
        # 1. 优先使用 rerank 分数
        for key in ("rerank_score", "relevance_score", "score"):
            value = metadata.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        # 2. 如果只有排名，也尽量转成一个可排序分数
        rrf_rank = metadata.get("rrf_rank")
        if rrf_rank is not None:
            try:
                rank_value = float(rrf_rank)
                if rank_value > 0:
                    # 排名越靠前，分数越高
                    return 1.0 / rank_value
            except (TypeError, ValueError):
                pass

        # 3. 最后兜底
        try:
            return float(getattr(item, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _wrap_items(self, items: Iterable[Any], source: str) -> list[ContextCandidate]:
        """
        把检索结果统一包装成 ContextCandidate。

        这一层不关心 item 原来是 Document、dict 还是字符串，
        只负责把文本、分数和 metadata 统一整理出来。
        """
        candidates: list[ContextCandidate] = []

        for idx, item in enumerate(items):
            content = self._to_text(item)
            if not content:
                continue

            metadata = self._to_metadata(item)
            score = self._extract_score(item, metadata)

            candidates.append(
                ContextCandidate(
                    source=source,
                    content=content,
                    score=score,
                    metadata={
                        **metadata,
                        # rank_hint 只是调试用，方便你追踪原始位置
                        "rank_hint": idx,
                    },
                )
            )

        return candidates


    def gather(self, question: str, session_id: str, top_k: int = 8) -> tuple[list[ContextCandidate], list[dict[str, Any]]]:
        """
        收集候选上下文。

        返回：
        - candidates：原始候选
        - history：结构化历史
        """
        candidates: list[ContextCandidate] = []
        history = self._load_history(session_id)

        # 历史也作为候选的一部分，方便后续统一筛选
        for item in history:
            candidates.append(
                ContextCandidate(
                    source="history",
                    content=f"{item['role']}: {item['content']}",
                    score=0.0,
                    metadata=item.get("metadata", {}),
                )
            )

        # 知识库检索结果
        if self.knowledge_retriever is not None:
            try:
                knowledge_items = list(self.knowledge_retriever(question, top_k))
                candidates.extend(self._wrap_items(knowledge_items, "knowledge"))
            except Exception:
                # 这里不让检索失败直接打断整个上下文构建
                pass

        # 父块检索结果
        if self.parent_chunk_retriever is not None:
            try:
                parent_items = list(self.parent_chunk_retriever(question, top_k))
                candidates.extend(self._wrap_items(parent_items, "parent_chunk"))
            except Exception:
                pass
                # 旧结构化笔记也作为候选上下文加入
        notes = self._load_notes(session_id)
        for item in notes:
            title = item.get("title", "")
            content = item.get("content", "")
            merged = f"{title}: {content}" if title else content

            candidates.append(
                ContextCandidate(
                    source="note",
                    content=merged,
                    score=float(item.get("importance", 0.5) or 0.5),
                    metadata={
                        "kind": item.get("kind", "note"),
                        "tags": item.get("tags", []),
                        **(item.get("metadata", {}) or {}),
                    },
                )
            )

        # 新结构化记忆（语义筛选后）
        memories = self._load_memories(question, session_id)
        for item in memories:
            title = item.get("title", "")
            content = item.get("content", "")
            merged = f"[Memory:{item.get('kind', '')}] {title}: {content}" if title else content

            candidates.append(
                ContextCandidate(
                    source="memory",
                    content=merged,
                    score=float(item.get("importance", 0.9) or 0.9),
                    metadata={
                        "kind": item.get("kind", "note"),
                        "tags": item.get("tags", []),
                        "source": "memory_system",
                        **(item.get("metadata", {}) or {}),
                    },
                )
            )

        # 这里简单按分数排序一下，后续阶段再做更复杂的筛选
        return candidates, history
