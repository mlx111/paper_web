from app.evaluation.failure_classifier import classify_failure
from app.evaluation.types import EvaluationCase, EvaluationResult


def _case(**overrides):
    data = {
        "id": "case-1",
        "question": "question",
        "expected_tools": [],
        "expected_tool_args": {},
        "expected_evidence": [],
        "must_include": [],
        "must_not_include": [],
    }
    data.update(overrides)
    return EvaluationCase(**data)


def _result(**overrides):
    data = {
        "case_id": "case-1",
        "question": "question",
        "mode": "deep",
        "expected_route": "deep",
        "score": 0.5,
        "route_correct": True,
        "tool_correct": True,
        "tool_args_correct": True,
        "keyword_hit": True,
        "evidence_hit": True,
        "must_include_hit": True,
        "must_not_include_hit": True,
        "context_mode_correct": True,
    }
    data.update(overrides)
    return EvaluationResult(**data)


def test_classifies_passed_result_as_none():
    category, reason = classify_failure(_case(), _result(score=0.9))

    assert category == "none"
    assert reason == ""


def test_classifies_tool_error_from_trace_summary():
    result = _result(
        trace_summary={
            "trace_status": "completed",
            "failed_steps": [
                {
                    "step_name": "tool:web_search",
                    "step_type": "tool",
                    "error": "timeout",
                }
            ],
            "tool_error_codes": ["TOOL_TIMEOUT"],
        }
    )

    category, reason = classify_failure(_case(expected_tools=["web_search"]), result)

    assert category == "tool_error"
    assert "TOOL_TIMEOUT" in reason


def test_classifies_tool_error_from_string_failed_steps():
    result = _result(
        trace_summary={
            "trace_status": "failed",
            "failed_steps": ["tool:web_search"],
            "tool_error_codes": [],
        }
    )

    category, reason = classify_failure(_case(expected_tools=["web_search"]), result)

    assert category == "tool_error"
    assert reason == "tool step failed"


def test_classifies_mcp_tool_error_from_string_failed_steps():
    result = _result(
        trace_summary={
            "trace_status": "failed",
            "failed_steps": ["mcp:mypaper_web_search"],
            "tool_error_codes": [],
        }
    )

    category, reason = classify_failure(_case(expected_tools=["mypaper_web_search"]), result)

    assert category == "tool_error"
    assert reason == "tool step failed"


def test_classifies_tool_selection_before_answer_quality():
    category, reason = classify_failure(
        _case(expected_tools=["web_search"]),
        _result(tool_correct=False, actual_tools=[]),
    )

    assert category == "tool_selection_error"
    assert "web_search" in reason


def test_classifies_tool_argument_error():
    category, reason = classify_failure(
        _case(expected_tool_args={"web_search": {"query": "agent"}}),
        _result(tool_args_correct=False, actual_tools=["web_search"]),
    )

    assert category == "tool_argument_error"
    assert "web_search" in reason


def test_classifies_evidence_ignored_when_evidence_hit_but_answer_terms_missing():
    category, reason = classify_failure(
        _case(expected_evidence=["paper"], must_include=["benchmark"]),
        _result(evidence_hit=True, must_include_hit=False),
    )

    assert category == "evidence_ignored"
    assert "must_include" in reason


def test_classifies_high_cost():
    category, reason = classify_failure(
        _case(),
        _result(token_usage=9001, latency_ms=100),
    )

    assert category == "high_cost"
    assert "9001" in reason
