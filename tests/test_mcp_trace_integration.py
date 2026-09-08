import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import mcp_tools
from services.run_trace_service import RunTraceService


class FakeResult:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return dict(self.payload)


class FakeWrapper:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self, tool_name, args):
        if self.error is not None:
            raise self.error
        return self.result


def _success_result():
    return FakeResult({
        "ok": True,
        "data": {"value": "ok"},
        "summary": "tool completed",
        "error": "",
        "error_code": "",
        "truncated": False,
        "truncated_from": 0,
    })


def test_successful_mcp_tool_call_creates_trace_run(monkeypatch, tmp_path):
    trace_service = RunTraceService(base_dir=tmp_path)
    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(_success_result()))

    payload = mcp_tools.call_mcp_tool(
        "mypaper_get_current_time",
        {"timezone": "Asia/Shanghai"},
        trace_service=trace_service,
    )

    assert payload["ok"] is True
    assert payload["trace"]["run_id"]
    trace = trace_service.load_run(payload["trace"]["run_id"])
    assert trace["route"] == "mcp"
    assert trace["status"] == "completed"
    assert trace["metadata"]["source"] == "mcp"
    assert trace["metadata"]["mcp_tool_name"] == "mypaper_get_current_time"
    assert trace["metadata"]["internal_tool_name"] == "get_current_time"
    assert len(trace["steps"]) == 1
    step = trace["steps"][0]
    assert step["step_name"] == "mcp:mypaper_get_current_time"
    assert step["step_type"] == "mcp_tool"
    assert step["status"] == "completed"
    assert step["input"]["arguments"] == {"timezone": "Asia/Shanghai"}
    assert step["output"]["ok"] is True
    assert step["output"]["summary"] == "tool completed"
    assert isinstance(step["output"]["data_size"], int)


def test_mcp_tool_exception_marks_trace_failed(monkeypatch, tmp_path):
    trace_service = RunTraceService(base_dir=tmp_path)
    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(error=RuntimeError("boom")))

    payload = mcp_tools.call_mcp_tool(
        "mypaper_get_current_time",
        {},
        trace_service=trace_service,
    )

    assert payload["ok"] is False
    assert payload["error_code"] == "TOOL_EXECUTION_ERROR"
    trace = trace_service.load_run(payload["trace"]["run_id"])
    assert trace["status"] == "failed"
    step = trace["steps"][0]
    assert step["status"] == "failed"
    assert "boom" in step["error"]
    assert step["output"]["error_code"] == "TOOL_EXECUTION_ERROR"


def test_invalid_mcp_args_are_traced_without_executing_tool(monkeypatch, tmp_path):
    trace_service = RunTraceService(base_dir=tmp_path)

    def should_not_execute(internal_name):
        raise AssertionError("invalid args should not build or execute a wrapper")

    monkeypatch.setattr(mcp_tools, "_get_wrapper", should_not_execute)

    payload = mcp_tools.call_mcp_tool(
        "mypaper_web_search",
        {"query": "agent", "count": 11},
        trace_service=trace_service,
    )

    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_ARGS"
    trace = trace_service.load_run(payload["trace"]["run_id"])
    assert trace["status"] == "failed"
    step = trace["steps"][0]
    assert step["status"] == "failed"
    assert step["output"]["error_code"] == "INVALID_ARGS"


def test_mcp_trace_redacts_sensitive_arguments(monkeypatch, tmp_path):
    trace_service = RunTraceService(base_dir=tmp_path)
    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(_success_result()))

    payload = mcp_tools.call_mcp_tool(
        "mypaper_get_current_time",
        {"timezone": "Asia/Shanghai", "api_key": "secret", "token": "abc"},
        trace_service=trace_service,
    )

    trace = trace_service.load_run(payload["trace"]["run_id"])
    args = trace["steps"][0]["input"]["arguments"]
    assert args["timezone"] == "Asia/Shanghai"
    assert args["api_key"] == "***"
    assert args["token"] == "***"
