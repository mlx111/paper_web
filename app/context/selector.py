from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .types import ContextCandidate, ContextEvidence


def _tokenize(text: str) -> set[str]:
    """
    一个非常轻量的分词策略。

    这里不是为了做“完美检索”，
    只是为了在没有真实 rerank 分数时，
    还能有一个稳定的兜底排序方式。
    """
    return {token for token in text.lower().replace("\n", " ").split() if token.strip()}


class ContextSelector:
    """
    Selector 的职责不是检索，而是“挑证据”。

    它的优先级是：
    1. 优先使用上游传下来的真实分数
    2. 如果没有真实分数，就用 rerank_fn
    3. 如果 rerank_fn 也不可用，就退回启发式排序
    """

    def __init__(
        self,
        rerank_fn: Callable[[str, list[str], int], Any] | None = None,
        min_score: float = 0.0,
    ):
        # 如果你想让 Selector 自己调用 rerank 服务，就在这里传 rerank_fn。
        # 如果上游已经把 rerank_score 填进 candidate.score，这里可以保持 None。
        self.rerank_fn = rerank_fn
        self.min_score = min_score

    def _heuristic_score(self, question: str, content: str) -> float:
        """
        没有真实分数时的兜底打分。

        逻辑很简单：
        - 统计 question 和 content 的 token 重合度
        - 重合越多，分数越高
        """
        q_tokens = _tokenize(question)
        c_tokens = _tokenize(content)
        if not q_tokens or not c_tokens:
            return 0.0

        overlap = len(q_tokens & c_tokens)
        coverage = overlap / max(len(q_tokens), 1)
        return float(overlap + coverage)

    def _normalize_score(self, candidate: ContextCandidate) -> float:
        """
        统一取分数。

        这里按优先级依次尝试：
        1. candidate.score
        2. metadata 里的 rerank_score
        3. metadata 里的 relevance_score
        4. metadata 里的 score
        5. 兜底 0.0
        """
        metadata = candidate.metadata or {}

        for key in ("rerank_score", "relevance_score", "score"):
            value = metadata.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        try:
            return float(candidate.score or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _score_candidate(self, question: str, candidate: ContextCandidate) -> tuple[float, str]:
        """
        给单个候选项打分，并返回分数来源。

        返回值：
        - score：最终用于排序的分数
        - score_source：分数来源，用于调试
        """
        normalized = self._normalize_score(candidate)
        if normalized > 0:
            return normalized, "rerank_or_metadata"

        # 没有真实分数时，才用启发式分数
        heuristic = self._heuristic_score(question, candidate.content)
        return heuristic, "heuristic"

    def _fallback_rank(self, question: str, candidates: list[ContextCandidate], top_k: int) -> list[ContextCandidate]:
        """
        没有 rerank 时使用的兜底排序。

        这里会优先使用 candidate.score，
        如果没有，就用启发式分数。
        """
        ranked: list[ContextCandidate] = []

        for idx, candidate in enumerate(candidates):
            score, score_source = self._score_candidate(question, candidate)

            if score < self.min_score:
                continue

            ranked.append(
                replace(
                    candidate,
                    score=score,
                    metadata={
                        **(candidate.metadata or {}),
                        "score_source": score_source,
                        "rank_hint": idx,
                    },
                )
            )

        # 这里保持稳定排序：
        # 分数高的排前面，分数相同的时候保留原始顺序的倾向
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _apply_rerank(self, candidates: list[ContextCandidate], ranked_result: Any, top_k: int) -> list[ContextCandidate]:
        """
        把 rerank 服务返回的结果映射回原始候选。

        兼容几种常见返回格式：
        - dict list：包含 index / relevance_score
        - tuple list：包含 (index, score)
        """
        selected: list[ContextCandidate] = []

        if not ranked_result:
            return selected

        if isinstance(ranked_result, list):
            # 形式 1：[{index: 0, relevance_score: 0.92}, ...]
            if ranked_result and isinstance(ranked_result[0], dict):
                for item in ranked_result[:top_k]:
                    idx = int(item.get("index", -1))
                    if 0 <= idx < len(candidates):
                        score = item.get("relevance_score", candidates[idx].score)
                        try:
                            score = float(score)
                        except (TypeError, ValueError):
                            score = float(candidates[idx].score or 0.0)

                        selected.append(
                            replace(
                                candidates[idx],
                                score=score,
                                metadata={
                                    **(candidates[idx].metadata or {}),
                                    "score_source": "rerank_fn",
                                    "rerank_score": score,
                                    "selected_index": idx,
                                },
                            )
                        )
                return selected

            # 形式 2：[(0, 0.92), (3, 0.88), ...]
            if ranked_result and isinstance(ranked_result[0], (tuple, list)):
                for item in ranked_result[:top_k]:
                    idx = int(item[0])
                    if 0 <= idx < len(candidates):
                        score = item[1] if len(item) > 1 else candidates[idx].score
                        try:
                            score = float(score)
                        except (TypeError, ValueError):
                            score = float(candidates[idx].score or 0.0)

                        selected.append(
                            replace(
                                candidates[idx],
                                score=score,
                                metadata={
                                    **(candidates[idx].metadata or {}),
                                    "score_source": "rerank_fn",
                                    "rerank_score": score,
                                    "selected_index": idx,
                                },
                            )
                        )
                return selected

        return selected

    def select(self, question: str, candidates: list[ContextCandidate], top_k: int = 6) -> list[ContextEvidence]:
        """
        从候选里挑出最终证据。

        优先级：
        1. 如果传了 rerank_fn，就优先用 rerank_fn 的结果
        2. 如果没有 rerank_fn，就直接用 candidate.score
        3. 如果 candidate.score 也没有，再退回启发式排序
        """
        if not candidates:
            return []

        selected_candidates: list[ContextCandidate] = []

        # 第一优先级：如果你显式传了 rerank_fn，就让它参与排序
        if self.rerank_fn is not None:
            try:
                documents = [candidate.content for candidate in candidates]
                ranked_result = self.rerank_fn(question, documents, top_k)
                selected_candidates = self._apply_rerank(candidates, ranked_result, top_k)
            except Exception:
                # rerank 失败时不要让整条链断掉，直接退回到 candidate.score
                selected_candidates = []

        # 第二优先级：如果 rerank_fn 没有可用结果，就用 candidate.score
        if not selected_candidates:
            selected_candidates = self._fallback_rank(question, candidates, top_k)

        evidence: list[ContextEvidence] = []
        for rank, candidate in enumerate(selected_candidates, start=1):
            final_score = self._normalize_score(candidate)

            evidence.append(
                ContextEvidence(
                    source=candidate.source,
                    content=candidate.content,
                    score=final_score,
                    metadata={
                        **(candidate.metadata or {}),
                        # 方便后面排查为什么这条证据被保留
                        "selected_rank": rank,
                        "final_score": final_score,
                    },
                )
            )

        return evidence
