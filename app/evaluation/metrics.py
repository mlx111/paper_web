from __future__ import annotations

import re

from .types import EvaluationResult, EvaluationSummary


_EN_ZH_SYNONYMS: dict[str, list[str]] = {
    "retrieval": ["检索", "召回"],
    "retrieve": ["检索", "召回"],
    "context": ["上下文"],
    "compress": ["压缩", "裁剪"],
    "history": ["历史"],
    "document": ["文档"],
    "note": ["笔记", "记忆"],
    "notes": ["笔记", "记忆"],
    "constraint": ["约束", "限制"],
    "rag": ["rag", "检索增强"],
    "search": ["搜索"],
    "time": ["时间"],
    "evidence": ["证据", "依据"],
    "keyword": ["关键词", "关键字"],
    "evaluation": ["评估", "评价"],
    "metric": ["指标", "度量"],
    "benchmark": ["基准"],
    "analysis": ["分析"],
    "summary": ["总结", "摘要"],
    "filter": ["过滤", "筛选"],
    "ranking": ["排序", "排名"],
    "boost": ["提升", "加权"],
}


def _expand_keywords(keywords: list[str]) -> list[str]:
    """Expand English keywords with Chinese synonyms."""
    expanded: list[str] = []
    for kw in keywords:
        expanded.append(kw)
        kw_lower = kw.lower()
        if kw_lower in _EN_ZH_SYNONYMS:
            expanded.extend(_EN_ZH_SYNONYMS[kw_lower])
    return expanded


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def keyword_hit(answer_text: str, keywords: list[str]) -> bool:
    """判断回答里是否命中关键词，支持英文自动匹配中文同义词。"""
    if not keywords:
        return True

    text = _normalize_text(answer_text)
    expanded = _expand_keywords(keywords)
    return any(_normalize_text(kw) in text for kw in expanded)


def must_include_hit(answer_text: str, required_terms: list[str]) -> bool:
    """
    判断回答是否包含所有必须出现的词。
    """
    if not required_terms:
        return True

    text = _normalize_text(answer_text)
    return all(_normalize_text(term) in text for term in required_terms)


def must_not_include_hit(answer_text: str, forbidden_terms: list[str]) -> bool:
    """
    判断回答是否避开了不该出现的词。
    """
    if not forbidden_terms:
        return True

    text = _normalize_text(answer_text)
    return all(_normalize_text(term) not in text for term in forbidden_terms)


def tool_hit(actual_tools: list[str], expected_tools: list[str]) -> bool:
    """
    判断工具调用是否命中。
    """
    if not expected_tools:
        return True

    actual_set = {tool.strip().lower() for tool in actual_tools if tool}
    expected_set = {tool.strip().lower() for tool in expected_tools if tool}
    return expected_set.issubset(actual_set)


def tool_args_hit(
    actual_tool_calls: list[dict[str, object]],
    expected_args: dict[str, dict[str, str]],
) -> bool:
    """Check if tool calls have expected argument values.

    expected_args format: {"tool_name": {"arg_name": "expected_substring"}}
    """
    if not expected_args:
        return True

    def _matches(call: dict, tool_name: str, expected_kwargs: dict[str, str]) -> bool:
        if call.get("name", "").lower() != tool_name.lower():
            return False
        call_args = call.get("args", {}) or {}
        for arg_name, expected_value in expected_kwargs.items():
            actual_value = call_args.get(arg_name, "")
            if isinstance(actual_value, str) and expected_value.lower() in actual_value.lower():
                continue
            return False
        return True

    for tool_name, expected_kwargs in expected_args.items():
        if not any(_matches(c, tool_name, expected_kwargs) for c in actual_tool_calls):
            return False
    return True


def notes_used_hit(actual_notes_used: bool, expected_notes_used: bool | None) -> bool:
    """
    判断 notes 使用是否符合预期。

    如果 case 没有明确指定 expected_notes_used，就默认视为不考核。
    """
    if expected_notes_used is None:
        return True
    return actual_notes_used == expected_notes_used


def context_mode_hit(actual_context_mode: str, expected_context_mode: str | None) -> bool:
    """
    判断上下文模式是否符合预期。
    """
    if not expected_context_mode:
        return True
    return (actual_context_mode or "").strip().lower() == expected_context_mode.strip().lower()


def calc_result_score(result: EvaluationResult) -> float:
    """
    单条样本的综合得分。
    """
    score = 0.0
    score += 0.20 if result.route_correct else 0.0
    score += 0.10 if result.tool_correct else 0.0
    score += 0.05 if result.tool_args_correct else 0.0
    score += 0.15 if result.keyword_hit else 0.0
    score += 0.10 if result.evidence_hit else 0.0
    score += 0.15 if result.must_include_hit else 0.0
    score += 0.10 if result.must_not_include_hit else 0.0
    score += 0.10 if result.notes_used else 0.0
    score += 0.05 if result.context_mode_correct else 0.0
    return round(score, 4)


def summarize(results: list[EvaluationResult]) -> EvaluationSummary:
    """
    汇总所有评估结果。
    """
    total = len(results)
    if total == 0:
        return EvaluationSummary(
            total_cases=0,
            passed_cases=0,
            route_accuracy=0.0,
            tool_accuracy=0.0,
            keyword_hit_rate=0.0,
            evidence_hit_rate=0.0,
            avg_latency_ms=0.0,
            avg_score=0.0,
            failed_cases=[],
        )

    passed_cases = sum(1 for item in results if item.score >= 0.75)
    route_accuracy = sum(1 for item in results if item.route_correct) / total
    tool_accuracy = sum(1 for item in results if item.tool_correct) / total
    tool_args_accuracy = sum(1 for item in results if item.tool_args_correct) / total
    keyword_hit_rate = sum(1 for item in results if item.keyword_hit) / total
    evidence_hit_rate = sum(1 for item in results if item.evidence_hit) / total
    avg_latency_ms = sum(item.latency_ms for item in results) / total
    avg_score = sum(item.score for item in results) / total
    failed_cases = [item for item in results if item.score < 0.75]

    return EvaluationSummary(
        total_cases=total,
        passed_cases=passed_cases,
        route_accuracy=round(route_accuracy, 4),
        tool_accuracy=round(tool_accuracy, 4),
        tool_args_accuracy=round(tool_args_accuracy, 4),
        keyword_hit_rate=round(keyword_hit_rate, 4),
        evidence_hit_rate=round(evidence_hit_rate, 4),
        avg_latency_ms=round(avg_latency_ms, 2),
        avg_score=round(avg_score, 4),
        failed_cases=failed_cases,
    )
