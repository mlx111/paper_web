"""语义缓存：DashScope embedding + 余弦相似度，SQLite 持久化。

Phase 6 成本优化：
- 仅用于 quick 轻量问答路径（深度研究/多智能体不缓存）
- 精确 hash 命中（零 embedding 开销）→ 语义命中（余弦 >= 阈值）
- 任一环节失败都静默降级为不缓存，绝不影响正常问答
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from pathlib import Path

from loguru import logger

from settings.config import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    embedding TEXT NOT NULL,
    answer TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_hash ON semantic_cache(query_hash);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_created ON semantic_cache(created_at);
"""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


class SemanticCacheService:
    """语义缓存（进程内单例）。lookup / store 永不抛异常。"""

    def __init__(self, db_path: str | None = None):
        path = Path(db_path or (Path(__file__).resolve().parents[1] / "data" / "semantic_cache.db"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("语义缓存初始化完成: {}（阈值 {:.2f}）", self.db_path, config.semantic_cache_threshold)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _embed(self, text: str) -> list[float] | None:
        try:
            from services.embodeding_service import embodeding_service

            vectors = embodeding_service.embed_query(text)
            return vectors[0] if vectors else None
        except Exception as exc:
            logger.warning("语义缓存 embedding 失败，降级为不缓存: {}", exc)
            return None

    def lookup(self, query: str) -> dict | None:
        """命中返回 {answer, model, similarity, cache_type}；未命中返回 None。"""
        text = _normalize(query)
        if not text or not config.semantic_cache_enabled:
            return None

        now = time.time()
        ttl_seconds = max(1, config.semantic_cache_ttl_hours) * 3600

        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT query_text, query_hash, embedding, answer, model, "
                    "prompt_tokens, completion_tokens, created_at "
                    "FROM semantic_cache ORDER BY id DESC LIMIT ?",
                    (config.semantic_cache_max_entries,),
                ).fetchall()
        except Exception as exc:
            logger.warning("语义缓存读取失败: {}", exc)
            return None

        if not rows:
            return None

        query_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()

        # 1) 精确 hash 命中（不做 embedding 调用）
        for row in rows:
            # 列序: query_text(0) query_hash(1) embedding(2) answer(3) model(4)
            #       prompt_tokens(5) completion_tokens(6) created_at(7)
            if row[1] == query_hash and now - float(row[7] or 0) <= ttl_seconds:
                logger.info("语义缓存精确命中，跳过 agent 调用")
                return {
                    "answer": row[3],
                    "model": row[4],
                    "similarity": 1.0,
                    "cache_type": "exact",
                    "cached_query": row[0],
                }

        # 2) 语义命中（embedding + 余弦）
        query_vec = self._embed(text)
        if query_vec is None:
            return None

        best = None
        for row in rows:
            created_at = float(row[7] or 0)
            if now - created_at > ttl_seconds:
                continue
            try:
                cached_vec = json.loads(row[2])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            similarity = _cosine(query_vec, cached_vec)
            if best is None or similarity > best[0]:
                best = (similarity, row)

        if best and best[0] >= config.semantic_cache_threshold:
            similarity, row = best
            logger.info(
                "语义缓存命中: similarity={:.3f} (阈值 {:.2f})，跳过 agent 调用",
                similarity,
                config.semantic_cache_threshold,
            )
            return {
                "answer": row[3],
                "model": row[4],
                "similarity": round(similarity, 4),
                "cache_type": "semantic",
                "cached_query": row[0],
            }
        return None

    def store(
        self,
        query: str,
        answer: str,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        text = _normalize(query)
        if not text or not answer or not config.semantic_cache_enabled:
            return
        vec = self._embed(text)
        if vec is None:
            return
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO semantic_cache "
                    "(query_text, query_hash, embedding, answer, model, prompt_tokens, completion_tokens, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        text,
                        hashlib.sha1(text.encode("utf-8")).hexdigest(),
                        json.dumps(vec),
                        answer,
                        model or "",
                        int(prompt_tokens or 0),
                        int(completion_tokens or 0),
                        time.time(),
                    ),
                )
                self._evict(conn)
        except Exception as exc:
            logger.warning("语义缓存写入失败: {}", exc)

    def _evict(self, conn: sqlite3.Connection) -> None:
        # TTL 过期 + 容量上限（保留最新 N 条）
        ttl_seconds = max(1, config.semantic_cache_ttl_hours) * 3600
        conn.execute("DELETE FROM semantic_cache WHERE created_at < ?", (time.time() - ttl_seconds,))
        conn.execute(
            "DELETE FROM semantic_cache WHERE id NOT IN ("
            "SELECT id FROM semantic_cache ORDER BY id DESC LIMIT ?)",
            (config.semantic_cache_max_entries,),
        )

    def stats(self) -> dict:
        try:
            with self._lock, self._connect() as conn:
                total = conn.execute("SELECT COUNT(*) FROM semantic_cache").fetchone()[0]
            return {"entries": total, "enabled": config.semantic_cache_enabled}
        except Exception:
            return {"entries": 0, "enabled": config.semantic_cache_enabled}


semantic_cache_service = SemanticCacheService()
