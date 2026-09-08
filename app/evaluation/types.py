from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvaluationCase:
    """
    单条评估样本。
    """
    id: str
    question: str
    mode: str = "deep"
    expected_route: str = "deep"
    expected_tools: list[str] = field(default_factory=list)
    expected_tool_args: dict[str, dict[str, str]] = field(default_factory=dict)
    expected_keywords: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    expected_answer_type: str = "analysis"
    difficulty: str = "medium"
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    expected_notes_used: bool | None = None
    expected_context_mode: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvaluationResult:
    """
    单条样本的评估结果。
    """
    case_id: str
    question: str
    mode: str
    expected_route: str
    actual_route: str = ""
    expected_tools: list[str] = field(default_factory=list)
    actual_tools: list[str] = field(default_factory=list)
    answer_text: str = ""
    latency_ms: float = 0.0
    token_usage: int = 0
    route_correct: bool = False
    tool_correct: bool = False
    tool_args_correct: bool = False
    keyword_hit: bool = False
    evidence_hit: bool = False
    must_include_hit: bool = False
    must_not_include_hit: bool = False
    notes_used: bool = False
    context_mode_correct: bool = False
    actual_context_mode: str = ""
    error: str = ""
    score: float = 0.0
    run_id: str = ""
    trace_path: str = ""
    failure_category: str = ""
    failure_reason: str = ""
    trace_summary: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)



@dataclass(slots=True)
class EvaluationSummary:
    """
    评估汇总结果。
    """
    total_cases: int
    passed_cases: int
    route_accuracy: float
    tool_accuracy: float
    tool_args_accuracy: float
    keyword_hit_rate: float
    evidence_hit_rate: float
    avg_latency_ms: float
    avg_score: float
    failed_cases: list[EvaluationResult] = field(default_factory=list)
