from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ContextConfig:
    """
    上下文工程的统一配置。

    这里的目标很简单：
    把所有上下文预算都集中到一个地方管理，
    后面不管是 gather、select、structure、compress 还是 assemble，
    都只看这一份配置。
    """

    # 单次上下文构建允许的大致 token 总预算
    max_tokens: int = 3000

    # 预留比例，避免把上下文塞得太满，给系统提示和模型自身输出留空间
    reserve_ratio: float = 0.2

    # 证据最低相关性阈值，低于这个值的内容可以忽略
    min_relevance: float = 0.1

    # 是否启用压缩
    enable_compression: bool = True

    # 压缩时对“新近性”和“相关性”的权重
    recency_weight: float = 0.3
    relevance_weight: float = 0.7

    # 最近会话消息保留多少条
    max_history_messages: int = 12

    # 组装时保留多少轮历史
    max_history_turns: int = 6

    # 最多保留多少条证据
    max_evidence_items: int = 6

    # 最终上下文最大字符数
    max_chars: int = 12000
    
    # 最多保留多少条笔记
    max_note_items: int = 4


    def __post_init__(self) -> None:
        """初始化后做一下参数校验，避免配置写错后悄悄出问题。"""
        assert 0.0 <= self.reserve_ratio <= 1.0, "reserve_ratio 必须在 [0, 1] 范围内"
        assert 0.0 <= self.min_relevance <= 1.0, "min_relevance 必须在 [0, 1] 范围内"
        assert abs(self.recency_weight + self.relevance_weight - 1.0) < 1e-6, (
            "recency_weight + relevance_weight 必须等于 1.0"
        )

    @property
    def usable_tokens(self) -> int:
        """
        真正可以用于上下文内容的 token 预算。

        这里会扣掉 reserve_ratio，避免上下文占满窗口。
        """
        return max(1, int(self.max_tokens * (1.0 - self.reserve_ratio)))
