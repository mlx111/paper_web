from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(slots=True)
class ContextPacket:
    """
    上下文包中的最小结构单元。

    它可以来自：
    - 历史消息
    - 检索证据
    - 路由提示
    - 结构化记忆

    这个类的作用是让上下文管线里的每一步都能用统一的数据结构传递信息。
    """
    source: str
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    token_count: int = 0
    relevance_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextCandidate:
    """
    Gatherer 收集到的原始候选项。

    这是“原料”阶段的数据，还没有经过真正的筛选和压缩。
    """
    source: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextEvidence:
    """
    Selector 挑出来的有效证据。

    这部分内容是后续真正准备给模型看的重点信息。
    """
    source: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextBundle:
    """
    最终输出给 agent 的上下文包。

    这是整个上下文工程管线的最终产物：
    Gather -> Select -> Structure -> Compress -> Assemble
    """
    question: str
    session_id: str
    mode: Literal["quick", "deep", "router"] = "deep"

    # 最终拼好的上下文文本，直接可以喂给 agent
    final_context: str = ""

    # 原始候选项，方便调试和回溯
    candidates: list[ContextCandidate] = field(default_factory=list)

    # 最终保留下来的关键证据
    evidence: list[ContextEvidence] = field(default_factory=list)

    # 结构化后的上下文片段
    packets: list[ContextPacket] = field(default_factory=list)

    # 会话历史
    history: list[dict[str, Any]] = field(default_factory=list)

    # 给路由器或 agent 的辅助提示
    routing_hints: list[str] = field(default_factory=list)

    # 调试追踪信息，方便排查上下文是怎么拼出来的
    trace: dict[str, Any] = field(default_factory=dict)
