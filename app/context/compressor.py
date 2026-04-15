from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable

from .context_config import ContextConfig
from context.types import ContextPacket


def _rough_token_count(text: str) -> int:
    """
    一个非常轻量的 token 估算方法。

    这里不引入额外 tokenizer，
    先用字符数近似控制预算。
    """
    if not text:
        return 0
    return max(1, len(text) // 2)


def _truncate_by_tokens(text: str, max_tokens: int) -> str:
    """
    按粗略 token 预算截断文本。

    这里本质上还是字符裁剪，
    只是用 token 预算做控制。
    """
    if max_tokens <= 0 or not text:
        return ""

    char_budget = max(1, max_tokens * 2)
    if len(text) <= char_budget:
        return text

    return text[: max(1, char_budget - 3)] + "..."


class ContextCompressor:
    """
    Compress 阶段。

    这个阶段的目标不是“直接删掉内容”，
    而是尽量把低价值信息先压成摘要，
    再把剩余内容控制在预算内。
    """

    def __init__(self, config: ContextConfig | None = None):
        self.config = config or ContextConfig()

    def _packet_kind(self, packet: ContextPacket) -> str:
        """
        判断一个 packet 属于哪一类。

        这里优先看 metadata 里的 kind，
        如果没有，再根据 source 做兜底判断。
        """
        metadata = packet.metadata or {}
        kind = metadata.get("kind")
        if kind:
            return str(kind)

        source = packet.source or ""
        if source == "question":
            return "user_question"
        if source == "mode_hint":
            return "mode_hint"
        if source == "history":
            return "conversation_history"
        if source.startswith("evidence:"):
            return "evidence"
        if source == "candidate_summary":
            return "candidate_summary"
        if source == "compressed_tail":
            return "compressed_tail"

        return "general"

    def _compress_lines(self, lines: list[str], head_keep: int = 2, tail_keep: int = 3) -> list[str]:
        """
        把一组文本行压成更短的摘要结构。

        策略很简单：
        - 去掉空行
        - 去掉重复行
        - 保留开头几行和结尾几行
        - 中间太长的部分用省略号代替
        """
        cleaned: list[str] = []
        seen: set[str] = set()

        for line in lines:
            text = line.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)

        if len(cleaned) <= head_keep + tail_keep + 1:
            return cleaned

        return cleaned[:head_keep] + ["..."] + cleaned[-tail_keep:]

    def _make_history_digest(self, packets: list[ContextPacket]) -> ContextPacket | None:
        """
        把多条历史 packet 压成一个 history_digest。

        这里不是简单截断，而是做“摘要式保留”：
        - 保留少量开头历史
        - 保留少量结尾历史
        - 中间过长部分压缩掉
        """
        if not packets:
            return None

        lines: list[str] = []
        latest_time = None
        max_score = 0.0

        for packet in packets:
            if latest_time is None or packet.timestamp > latest_time:
                latest_time = packet.timestamp
            if float(packet.relevance_score or 0.0) > max_score:
                max_score = float(packet.relevance_score or 0.0)

            for line in (packet.content or "").splitlines():
                text = line.strip()
                if text:
                    lines.append(text)

        compact_lines = self._compress_lines(lines, head_keep=2, tail_keep=3)
        if not compact_lines:
            return None

        content = "最近会话摘要：\n" + "\n".join(f"- {line}" for line in compact_lines)
        return ContextPacket(
            source="history_digest",
            content=content,
            timestamp=latest_time or datetime.utcnow(),
            token_count=_rough_token_count(content),
            relevance_score=max(0.6, max_score),
            metadata={
                "kind": "history_digest",
                "compressed": True,
                "compressed_from": "conversation_history",
                "packet_count": len(packets),
            },
        )

    def _make_tail_digest(self, packets: list[ContextPacket]) -> ContextPacket | None:
        """
        把剩余的低优先级 packet 压成一个尾部摘要。

        这样做的好处是：
        - 不会直接丢掉信息
        - 能保留“还有哪些内容被看过”的痕迹
        - 对长文档和长对话更稳
        """
        if not packets:
            return None

        lines: list[str] = []
        latest_time = None
        max_score = 0.0

        for packet in packets:
            if latest_time is None or packet.timestamp > latest_time:
                latest_time = packet.timestamp
            if float(packet.relevance_score or 0.0) > max_score:
                max_score = float(packet.relevance_score or 0.0)

            snippet = (packet.content or "").replace("\n", " ").strip()
            if len(snippet) > 72:
                snippet = snippet[:69] + "..."

            lines.append(f"- [{packet.source}] {snippet}")

        content = "其余相关内容摘要：\n" + "\n".join(lines)
        return ContextPacket(
            source="compressed_tail",
            content=content,
            timestamp=latest_time or datetime.utcnow(),
            token_count=_rough_token_count(content),
            relevance_score=max(0.3, max_score * 0.7),
            metadata={
                "kind": "compressed_tail",
                "compressed": True,
                "packet_count": len(packets),
            },
        )

    def _fit_packet(self, packet: ContextPacket, remaining_tokens: int) -> ContextPacket | None:
        """
        把一个 packet 尽量塞进剩余预算里。

        如果完整放不下，就截断成一个更短的版本。
        """
        if remaining_tokens <= 0:
            return None

        token_count = packet.token_count or _rough_token_count(packet.content)
        if token_count <= remaining_tokens:
            return packet

        truncated_content = _truncate_by_tokens(packet.content, remaining_tokens)
        if not truncated_content:
            return None

        return replace(
            packet,
            content=truncated_content,
            token_count=_rough_token_count(truncated_content),
            metadata={
                **(packet.metadata or {}),
                "compressed": True,
                "compressed_at": datetime.utcnow().isoformat(),
            },
        )

    def compress(self, packets: Iterable[ContextPacket]) -> list[ContextPacket]:
        """
        压缩 packets，使其尽量落在预算内。

        压缩优先级：
        1. 先保留锚点信息：问题、模式提示
        2. 把历史压成摘要
        3. 保留高价值证据
        4. 把剩余内容压成尾部摘要
        5. 最后才做截断兜底
        """
        packet_list = list(packets)
        if not packet_list:
            return []

        if not self.config.enable_compression:
            return packet_list

        budget = self.config.usable_tokens
        kept: list[ContextPacket] = []
        used = 0

        anchors: list[ContextPacket] = []
        history_packets: list[ContextPacket] = []
        evidence_packets: list[ContextPacket] = []
        tail_packets: list[ContextPacket] = []

        # 先把不同类型的 packet 分开，后面好按优先级处理
        for packet in packet_list:
            kind = self._packet_kind(packet)

            if kind in ("user_question", "mode_hint"):
                anchors.append(packet)
            elif kind in ("conversation_history", "history"):
                history_packets.append(packet)
            elif kind == "evidence":
                evidence_packets.append(packet)
            else:
                tail_packets.append(packet)

        # 锚点先保留：问题和模式提示最重要
        def anchor_priority(packet: ContextPacket) -> int:
            kind = self._packet_kind(packet)
            if kind == "user_question":
                return 0
            if kind == "mode_hint":
                return 1
            return 2

        anchors.sort(key=anchor_priority)

        for packet in anchors:
            fitted = self._fit_packet(packet, budget - used)
            if fitted is None:
                continue
            kept.append(fitted)
            used += fitted.token_count or _rough_token_count(fitted.content)

        # 历史不要直接堆原文，先压成一个摘要 packet
        history_digest = self._make_history_digest(history_packets)
        if history_digest is not None:
            fitted = self._fit_packet(history_digest, budget - used)
            if fitted is not None:
                kept.append(fitted)
                used += fitted.token_count or _rough_token_count(fitted.content)

        # 证据按相关性排序，优先保留高价值内容
        evidence_packets.sort(
            key=lambda p: (
                float(p.relevance_score or 0.0),
                p.timestamp,
            ),
            reverse=True,
        )

        remaining_evidence: list[ContextPacket] = []
        for packet in evidence_packets:
            fitted = self._fit_packet(packet, budget - used)
            if fitted is None:
                remaining_evidence.append(packet)
                continue

            kept.append(fitted)
            used += fitted.token_count or _rough_token_count(fitted.content)

        # 如果还有低优先级内容没放下，就压成一个尾部摘要
        overflow_packets = remaining_evidence + tail_packets
        if overflow_packets and used < budget:
            tail_digest = self._make_tail_digest(overflow_packets)
            if tail_digest is not None:
                fitted = self._fit_packet(tail_digest, budget - used)
                if fitted is not None:
                    kept.append(fitted)
                    used += fitted.token_count or _rough_token_count(fitted.content)

        # 保险起见，再按当前预算做一次最终裁剪
        final_packets: list[ContextPacket] = []
        final_used = 0
        for packet in kept:
            token_count = packet.token_count or _rough_token_count(packet.content)
            if final_used + token_count <= budget:
                final_packets.append(packet)
                final_used += token_count
                continue

            fitted = self._fit_packet(packet, budget - final_used)
            if fitted is not None:
                final_packets.append(fitted)
                final_used += fitted.token_count or _rough_token_count(fitted.content)
                break

        return final_packets
