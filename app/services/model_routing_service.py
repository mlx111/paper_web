"""意图感知的模型路由：简单问题走廉价模型，复杂问题走默认模型。

Phase 6 成本优化：
- 复用 query_intent_service 的正则意图分类（零 LLM 延迟）
- ENTITY（作者/发表信息）与短寒暄 → 廉价模型（qwen-turbo 级）
- TEMPORAL / LITERATURE（需要检索与综合）→ 默认模型
- 通过 MODEL_ROUTING_ENABLED 环境变量开关，A/B 评测时切换
"""

from __future__ import annotations

import re

from loguru import logger

from services.query_intent_service import QueryIntent, QueryIntentService

# 复杂信号：出现即视为复杂问题（即使字数少）
_COMPLEX_HINT = re.compile(
    r"(比较|分析|总结|综述|为什么|如何|怎么|区别|评价|影响|方法|"
    r"compare|analyze|summar|survey|why|how|difference|review|trade[- ]?off)",
    re.IGNORECASE,
)


class ModelRoutingService:
    """按意图与长度把 quick 问答路由到不同档位的模型。"""

    def __init__(self, intent_service: QueryIntentService | None = None):
        self.intent_service = intent_service or QueryIntentService()

    def is_simple_query(self, query: str) -> tuple[bool, str]:
        """返回 (是否简单, 路由原因)。"""
        text = (query or "").strip()
        if not text:
            return True, "empty"

        intent = self.intent_service.classify(text)

        # 学术 qa 数据集里即便「实体类」问题也常需 RAG 检索，
        # 只有极短的一句话事实问答才下沉到廉价模型（保守路由，保通过率）
        if intent == QueryIntent.ENTITY and len(text) <= 18:
            # 短实体问答（谁写的/哪年发表）答案短且确定性强
            return True, f"intent={intent.value},len={len(text)}"
        if intent in (QueryIntent.TEMPORAL, QueryIntent.LITERATURE):
            # 检索/综述类需要更强的综合能力
            return False, f"intent={intent.value}"
        if _COMPLEX_HINT.search(text):
            return False, "complex_hint"

        # 普通 GENERAL：短寒暄/一句话事实问答走小模型
        if len(text) <= 14:
            return True, f"short_general(len={len(text)})"
        return False, f"long_general(len={len(text)})"


model_routing_service = ModelRoutingService()
