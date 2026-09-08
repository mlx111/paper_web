from __future__ import annotations

from typing import Any

from .types import EvaluationCase, EvaluationResult


PASS_THRESHOLD = 0.75
HIGH_TOKEN_THRESHOLD = 8000
HIGH_LATENCY_MS_THRESHOLD = 60000


def classify_failure(case: EvaluationCase, result: EvaluationResult) -> tuple[str, str]:
    if result.score >= PASS_THRESHOLD:
        return "none", ""

    trace_summary = result.trace_summary or {}
    failed_steps = trace_summary.get("failed_steps") or []
    tool_error_codes = trace_summary.get("tool_error_codes") or []

    if _has_tool_failure(failed_steps, tool_error_codes):
        code_text = ", ".join(str(code) for code in tool_error_codes if code)
        reason = f"tool step failed"
        if code_text:
            reason = f"{reason}: {code_text}"
        return "tool_error", reason

    if result.error:
        return "runtime_error", result.error

    if str(trace_summary.get("trace_status") or "").lower() == "failed":
        return "runtime_error", "trace status is failed"

    if case.expected_tools and not result.tool_correct:
        missing = _missing_items(case.expected_tools, result.actual_tools)
        return "tool_selection_error", f"missing expected tools: {', '.join(missing)}"

    if case.expected_tool_args and not result.tool_args_correct:
        return "tool_argument_error", f"tool arguments did not match expected args for: {', '.join(case.expected_tool_args.keys())}"

    if case.expected_evidence and not result.evidence_hit:
        evidence_count = _context_evidence_count(result)
        if evidence_count <= 0:
            return "retrieval_miss", "expected evidence was not found and trace has no retrieved evidence"
        return "retrieval_miss", "expected evidence was not present in answer"

    if result.evidence_hit and (not result.keyword_hit or not result.must_include_hit):
        missed = []
        if not result.keyword_hit:
            missed.append("keyword")
        if not result.must_include_hit:
            missed.append("must_include")
        return "evidence_ignored", f"evidence was present but answer missed: {', '.join(missed)}"

    if not result.must_not_include_hit:
        return "hallucination_or_format_error", "answer contained forbidden terms"

    if result.token_usage > HIGH_TOKEN_THRESHOLD:
        return "high_cost", f"token_usage {result.token_usage} exceeded {HIGH_TOKEN_THRESHOLD}"

    if result.latency_ms > HIGH_LATENCY_MS_THRESHOLD:
        return "high_cost", f"latency_ms {result.latency_ms} exceeded {HIGH_LATENCY_MS_THRESHOLD}"

    return "low_answer_quality", "score below pass threshold"


def _has_tool_failure(failed_steps: Any, tool_error_codes: Any) -> bool:
    if tool_error_codes:
        return True
    if not isinstance(failed_steps, list):
        return False
    for step in failed_steps:
        if isinstance(step, str):
            step_name = step.lower()
            if step_name.startswith(("tool:", "mcp:")):
                return True
            continue
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("step_type") or "").lower()
        step_name = str(step.get("step_name") or "").lower()
        if step_type in {"tool", "mcp_tool"} or step_name.startswith(("tool:", "mcp:")):
            return True
    return False


def _missing_items(expected: list[str], actual: list[str]) -> list[str]:
    actual_set = {item.strip().lower() for item in actual if item}
    return [item for item in expected if item.strip().lower() not in actual_set]


def _context_evidence_count(result: EvaluationResult) -> int:
    context_trace = result.meta.get("context_trace") if isinstance(result.meta, dict) else {}
    if not isinstance(context_trace, dict):
        return 0
    for key in ("evidence_count", "retrieved_count", "chunk_count", "context_count"):
        try:
            return int(context_trace.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0
