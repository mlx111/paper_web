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
    
    # 最多保留多少条笔记（旧系统）
    max_note_items: int = 4

    # 最多保留多少条记忆（新结构化记忆系统，语义筛选后）
    max_memory_items: int = 4

    # 是否启用新记忆系统
    enable_structured_memory: bool = True

    # ---- Hermes-style 消息级压缩配置 ----

    # 是否启用 Hermes 风格的四阶段消息压缩
    enable_hermes_compression: bool = True

    # 上下文窗口 token 容量（用于计算压缩触发阈值）
    context_window_tokens: int = 32000

    # 消息总 token 数超过此比例时触发压缩
    compression_trigger_ratio: float = 0.5

    # Phase 2: 头部保护的消息条数（system prompt + 首次交换）
    head_protect_messages: int = 3

    # Phase 2: 尾部 token 预算（保护最近的上下文）
    tail_token_budget: int = 20000

    # Phase 3: 是否启用 LLM 结构化摘要
    summary_llm_enabled: bool = True

    # Phase 3: 送入摘要模型的文本上限（字符数）
    summary_prompt_limit: int = 8000

    # Phase 5: 防抖动 — 最小节省率，低于此值视为低效压缩
    anti_thrash_min_savings: float = 0.1

    # Phase 5: 连续低效压缩次数阈值，超过后触发警告
    anti_thrash_consecutive_limit: int = 2

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

    @property
    def compression_trigger_tokens(self) -> int:
        """
        当消息总 token 数超过此值时触发 Hermes 风格压缩。

        默认: 32000 * 0.5 = 16000 tokens
        """
        return max(1, int(self.context_window_tokens * self.compression_trigger_ratio))
