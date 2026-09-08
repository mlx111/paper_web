import asyncio
import json
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from evaluation.mcp_runner import MCPEvaluationRunner
from services.run_trace_service import RunTraceService


def test_mcp_evaluation_runner_records_trace_fields(monkeypatch, tmp_path):
    cases_path = tmp_path / "mcp_cases.json"
    cases_path.write_text(json.dumps([
        {
            "id": "mcp_time_ok",
            "tool_name": "mypaper_get_current_time",
            "args": {"timezone": "Asia/Shanghai"},
            "expect_ok": True,
            "expected_error_code": "",
            "description": "time tool should succeed and create trace"
        }
    ]), encoding="utf-8")

    trace_service = RunTraceService(base_dir=tmp_path / "traces")

    def fake_call_mcp_tool(tool_name, args, *, trace_service=None, trace_enabled=True):
        run = trace_service.start_run("mcp", "mcp", tool_name, metadata={
            "source": "mcp",
            "mcp_tool_name": tool_name,
            "internal_tool_name": "get_current_time",
        })
        with trace_service.step(run.run_id, f"mcp:{tool_name}", "mcp_tool") as step:
            step.set_input({"mcp_tool_name": tool_name, "arguments": args})
            step.set_output({"ok": True, "summary": "tool completed", "error_code": "", "data_size": 2})
        trace_service.end_run(run.run_id, status="completed")
        return {
            "ok": True,
            "data": "ok",
            "error": "",
            "error_code": "",
            "summary": "tool completed",
            "truncated": False,
            "truncated_from": 0,
            "trace": {"run_id": run.run_id, "trace_path": str(run.trace_path)},
        }

    import evaluation.mcp_runner as mcp_runner_module
    monkeypatch.setattr(mcp_runner_module, "call_mcp_tool", fake_call_mcp_tool)

    results, summary = asyncio.run(MCPEvaluationRunner(str(cases_path), trace_service=trace_service).run())

    assert summary.total_cases == 1
    assert summary.passed_cases == 1
    result = results[0]
    assert result.case_id == "mcp_time_ok"
    assert result.mode == "mcp"
    assert result.actual_route == "mcp"
    assert result.actual_tools == ["mypaper_get_current_time"]
    assert result.run_id
    assert result.trace_path.endswith(f"{result.run_id}.json")
    assert result.trace_summary["trace_status"] == "completed"
    assert result.trace_summary["mcp_tool_steps"] == ["mcp:mypaper_get_current_time"]
    assert result.meta["mcp_tool_name"] == "mypaper_get_current_time"
    assert result.meta["expected_ok"] is True
    assert result.meta["actual_ok"] is True


def test_mcp_evaluation_runner_fails_on_unexpected_error_code(monkeypatch, tmp_path):
    cases_path = tmp_path / "mcp_cases.json"
    cases_path.write_text(json.dumps([
        {
            "id": "mcp_invalid_args",
            "tool_name": "mypaper_web_search",
            "args": {"query": "agent", "count": 11},
            "expect_ok": False,
            "expected_error_code": "INVALID_ARGS"
        }
    ]), encoding="utf-8")

    trace_service = RunTraceService(base_dir=tmp_path / "traces")

    def fake_call_mcp_tool(tool_name, args, *, trace_service=None, trace_enabled=True):
        run = trace_service.start_run("mcp", "mcp", tool_name, metadata={"source": "mcp", "mcp_tool_name": tool_name})
        with trace_service.step(run.run_id, f"mcp:{tool_name}", "mcp_tool") as step:
            step.set_output({"ok": False, "error_code": "TOOL_EXECUTION_ERROR", "data_size": 0})
            step.mark_failed("wrong error")
        trace_service.end_run(run.run_id, status="failed", error="wrong error")
        return {
            "ok": False,
            "data": None,
            "error": "wrong error",
            "error_code": "TOOL_EXECUTION_ERROR",
            "summary": "",
            "truncated": False,
            "truncated_from": 0,
            "trace": {"run_id": run.run_id, "trace_path": str(run.trace_path)},
        }

    import evaluation.mcp_runner as mcp_runner_module
    monkeypatch.setattr(mcp_runner_module, "call_mcp_tool", fake_call_mcp_tool)

    results, summary = asyncio.run(MCPEvaluationRunner(str(cases_path), trace_service=trace_service).run())

    assert summary.total_cases == 1
    assert summary.passed_cases == 0
    result = results[0]
    assert result.score == 0.0
    assert result.failure_category == "mcp_error"
    assert "INVALID_ARGS" in result.failure_reason
    assert result.trace_summary["trace_status"] == "failed"
