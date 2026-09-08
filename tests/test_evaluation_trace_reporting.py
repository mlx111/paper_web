import json

from app.evaluation.reporter import write_json_report, write_markdown_report
from app.evaluation.types import EvaluationResult, EvaluationSummary


def test_reports_trace_and_failure_category_fields(tmp_path):
    result = EvaluationResult(
        case_id="case-1",
        question="question",
        mode="deep",
        expected_route="deep",
        actual_route="deep",
        expected_tools=["web_search"],
        actual_tools=["web_search"],
        token_usage=321,
        score=0.4,
        run_id="run-123",
        trace_path="runtime/run_traces/session/run-123.json",
        failure_category="tool_error",
        failure_reason="tool failed: timeout",
        trace_summary={
            "trace_status": "failed",
            "step_count": 2,
            "tool_steps": ["tool:web_search"],
            "tool_error_codes": ["TOOL_TIMEOUT"],
        },
    )
    summary = EvaluationSummary(
        total_cases=1,
        passed_cases=0,
        route_accuracy=1.0,
        tool_accuracy=1.0,
        tool_args_accuracy=1.0,
        keyword_hit_rate=0.0,
        evidence_hit_rate=0.0,
        avg_latency_ms=10.0,
        avg_score=0.4,
        failed_cases=[result],
    )

    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    write_json_report(json_path, summary, [result])
    write_markdown_report(md_path, summary, [result])

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["results"][0]["run_id"] == "run-123"
    assert payload["results"][0]["trace_path"].endswith("run-123.json")
    assert payload["results"][0]["failure_category"] == "tool_error"
    assert payload["results"][0]["trace_summary"]["tool_error_codes"] == ["TOOL_TIMEOUT"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "## Failure Categories" in markdown
    assert "tool_error: 1" in markdown
    assert "run-123" in markdown
    assert "runtime/run_traces/session/run-123.json" in markdown
    assert "token_usage=321" in markdown
