from __future__ import annotations

from typing import Literal

from .context_config import ContextConfig
from context.types import ContextBundle, ContextCandidate, ContextEvidence, ContextPacket


class ContextAssembler:
    """
    Assemble 阶段。

    这个阶段只负责“拼装”，不再做检索、不再做排序。
    """

    def __init__(self, config: ContextConfig | None = None):
        self.config = config or ContextConfig()
    def _has_packet_kind(self, packets: list[ContextPacket], kind: str) -> bool:
        """
        判断 packets 里是否已经存在某一种结构化内容。

        这里主要用于识别：
        - history_digest
        - compressed_tail

        有了这些摘要包以后，就不要再把完整历史重复展开。
        """
        for packet in packets:
            metadata = packet.metadata or {}
            if metadata.get("kind") == kind:
                return True
            if packet.source == kind:
                return True
        return False

    def _format_history(self, history: list[dict]) -> str:
        """把历史消息整理成简洁文本。"""
        if not history:
            return "无"

        lines = []
        for item in history[-self.config.max_history_turns:]:
            role = item.get("role", "assistant")
            content = (item.get("content") or "").strip()
            if content:
                lines.append(f"- {role}: {content}")
        return "\n".join(lines) if lines else "无"

    def _format_evidence(self, evidence: list[ContextEvidence]) -> str:
        """把证据整理成编号列表。"""
        if not evidence:
            return "无"

        lines = []
        for idx, item in enumerate(evidence[:self.config.max_evidence_items], start=1):
            source = item.source or "unknown"
            content = (item.content or "").strip()
            if content:
                lines.append(f"{idx}. [{source}] {content}")
        return "\n".join(lines) if lines else "无"

    def _format_packets(self, packets: list[ContextPacket]) -> str:
        """把结构化 packets 整理成可读文本。"""
        if not packets:
            return "无"

        lines = []
        for idx, packet in enumerate(packets, start=1):
            source = packet.source or "unknown"
            content = (packet.content or "").strip()
            if content:
                lines.append(f"{idx}. [{source}] {content}")
        return "\n".join(lines) if lines else "无"

    def _truncate(self, text: str) -> str:
        """最后做一次长度保护。"""
        if len(text) <= self.config.max_chars:
            return text
        return text[: self.config.max_chars - 3] + "..."

    def assemble_from_packets(
        self,
        question: str,
        session_id: str,
        history: list[dict],
        evidence: list[ContextEvidence],
        packets: list[ContextPacket],
        candidates: list[ContextCandidate] | None = None,
        mode: Literal["quick", "deep", "router"] = "deep",
    ) -> ContextBundle:
        """
        从 packets 组装最终上下文包。

        这里的关键点是：
        如果压缩层已经把历史整理成 history_digest，
        那这里就不要再把完整历史展开一遍，避免重复。
        """
        history_has_digest = self._has_packet_kind(packets, "history_digest")

        # 如果历史已经被压缩成摘要，这里就只做提示，不再展开完整历史
        if history_has_digest:
            history_text = "已压缩为结构化摘要，请直接查看下方【结构化上下文】中的 history_digest。"
        else:
            history_text = self._format_history(history)

        evidence_text = self._format_evidence(evidence)
        packets_text = self._format_packets(packets)

        sections = [
            f"【模式】{mode}",
            f"【会话ID】{session_id}",
            f"【用户问题】{question}",
            "",
            "【会话历史】",
            history_text,
            "",
            "【关键证据】",
            evidence_text,
            "",
            "【结构化上下文】",
            packets_text,
        ]

        if mode == "deep":
            sections.extend(
                [
                    "",
                    "【处理要求】",
                    "请优先基于证据回答；如信息不足，明确说明缺口；需要时给出分步骤分析。",
                ]
            )
        elif mode == "quick":
            sections.extend(
                [
                    "",
                    "【处理要求】",
                    "请直接给出简洁、可靠的回答，避免展开不必要的推导。",
                ]
            )
        else:
            sections.extend(
                [
                    "",
                    "【处理要求】",
                    "请根据当前问题判断路由倾向，只保留与路由相关的最小必要上下文。",
                ]
            )

        final_context = self._truncate("\n".join(sections).strip())
        note_count = 0
        if candidates:
            note_count = sum(1 for item in candidates if getattr(item, "source", "") == "note")

        return ContextBundle(
            question=question,
            session_id=session_id,
            mode=mode,
            final_context=final_context,
            candidates=candidates or [],
            evidence=evidence,
            packets=packets,
            history=history,
            routing_hints=[
                f"history_count={len(history)}",
                f"evidence_count={len(evidence)}",
                f"packet_count={len(packets)}",
                f"mode={mode}",
                f"note_count={note_count}",
            ],
            trace={
                "history_turns_used": min(len(history), self.config.max_history_turns),
                "evidence_items_used": min(len(evidence), self.config.max_evidence_items),
                "packet_items_used": len(packets),
                "note_count": note_count,
                "final_chars": len(final_context),
            },
        )


    def assemble(
        self,
        question: str,
        session_id: str,
        history: list[dict],
        evidence: list[ContextEvidence],
        candidates: list[ContextCandidate] | None = None,
        mode: Literal["quick", "deep", "router"] = "deep",
    ) -> ContextBundle:
        """
        兼容旧接口的包装方法。
        """
        packets = [
            ContextPacket(
                source=item.source,
                content=item.content,
                relevance_score=float(item.score or 0.0),
                metadata=item.metadata or {},
            )
            for item in evidence
        ]

        return self.assemble_from_packets(
            question=question,
            session_id=session_id,
            history=history,
            evidence=evidence,
            packets=packets,
            candidates=candidates,
            mode=mode,
        )
