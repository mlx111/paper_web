from __future__ import annotations

from datetime import datetime
from typing import Literal

from .context_config import ContextConfig
from context.types import ContextCandidate, ContextEvidence, ContextPacket


def _rough_token_count(text: str) -> int:
    """
    一个非常轻量的 token 估算方法。

    这里不引入额外 tokenizer，先用一个简单的字符预算近似。
    """
    if not text:
        return 0
    return max(1, len(text) // 2)


class ContextStructurer:
    """
    Structure 阶段。

    这个阶段不负责检索，也不负责压缩，
    只负责把已经选中的内容整理成更适合模型阅读的结构。
    """

    def __init__(self, config: ContextConfig | None = None):
        self.config = config or ContextConfig()

    def _history_packet(self, history: list[dict], session_id: str) -> ContextPacket | None:
        """
        把最近的会话历史整理成一个结构化包。
        """
        if not history:
            return None

        lines = []
        for item in history[-self.config.max_history_turns:]:
            role = item.get("role", "assistant")
            content = (item.get("content") or "").strip()
            if content:
                lines.append(f"- {role}: {content}")

        if not lines:
            return None

        content = "\n".join(lines)
        return ContextPacket(
            source="history",
            content=content,
            timestamp=datetime.utcnow(),
            token_count=_rough_token_count(content),
            relevance_score=0.6,
            metadata={
                "session_id": session_id,
                "items": len(lines),
                "kind": "conversation_history",
            },
        )

    def _question_packet(self, question: str, session_id: str, mode: str) -> ContextPacket:
        """
        用户当前问题始终是上下文里的锚点。
        """
        return ContextPacket(
            source="question",
            content=question,
            timestamp=datetime.utcnow(),
            token_count=_rough_token_count(question),
            relevance_score=1.0,
            metadata={
                "session_id": session_id,
                "mode": mode,
                "kind": "user_question",
            },
        )

    def _evidence_packet(self, item: ContextEvidence) -> ContextPacket:
        """
        把筛选后的证据转换成结构化包。
        """
        content = (item.content or "").strip()
        return ContextPacket(
            source=f"evidence:{item.source}",
            content=content,
            timestamp=datetime.utcnow(),
            token_count=_rough_token_count(content),
            relevance_score=float(item.score or 0.0),
            metadata={**(item.metadata or {}), "kind": "evidence"},
        )

    def _candidate_summary_packet(self, candidates: list[ContextCandidate]) -> ContextPacket | None:
        """
        把部分候选项做一个轻量摘要。

        这样能让模型知道“还有哪些东西被看过”，但不会把全部原文都塞进去。
        """
        if not candidates:
            return None

        top = candidates[: min(3, len(candidates))]
        lines = []
        for idx, item in enumerate(top, start=1):
            content = (item.content or "").strip()
            if content:
                lines.append(f"{idx}. [{item.source}] {content}")

        if not lines:
            return None

        content = "\n".join(lines)
        return ContextPacket(
            source="candidate_summary",
            content=content,
            timestamp=datetime.utcnow(),
            token_count=_rough_token_count(content),
            relevance_score=0.35,
            metadata={
                "kind": "candidate_summary",
                "items": len(lines),
            },
        )

    def _mode_hint_packet(self, mode: Literal["quick", "deep", "router"]) -> ContextPacket:
        """
        根据不同模式给模型一个很轻的行为提示。
        """
        if mode == "quick":
            hint = "优先给出简短、直接、可靠的回答，不要展开过多推导。"
        elif mode == "router":
            hint = "优先判断任务应该交给 quick 还是 deep。"
        else:
            hint = "优先基于证据做结构化、分步骤的回答。"

        return ContextPacket(
            source="mode_hint",
            content=hint,
            timestamp=datetime.utcnow(),
            token_count=_rough_token_count(hint),
            relevance_score=0.95,
            metadata={"kind": "mode_hint", "mode": mode},
        )

    def structure(
        self,
        question: str,
        session_id: str,
        history: list[dict],
        evidence: list[ContextEvidence],
        candidates: list[ContextCandidate] | None = None,
        mode: Literal["quick", "deep", "router"] = "deep",
    ) -> list[ContextPacket]:
        """
        把选中的内容整理成结构化 packets。

        这一步的目标是：让后面的压缩和组装更容易做。
        """
        packets: list[ContextPacket] = []

        # 1. 当前问题作为锚点
        packets.append(self._question_packet(question, session_id, mode))

        # 2. 最近历史
        history_packet = self._history_packet(history, session_id)
        if history_packet is not None:
            packets.append(history_packet)

        # 3. 关键证据
        for item in evidence[: self.config.max_evidence_items]:
            if float(item.score or 0.0) >= self.config.min_relevance:
                packets.append(self._evidence_packet(item))

        # 4. 候选摘要
        if candidates:
            summary_packet = self._candidate_summary_packet(candidates)
            if summary_packet is not None:
                packets.append(summary_packet)

        # 5. 模式提示
        packets.append(self._mode_hint_packet(mode))

        return packets
