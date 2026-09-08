import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import mcp_tools


class FakeResult:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return dict(self.payload)


class FakeWrapper:
    def __init__(self, execute):
        self.execute = execute


def test_call_mcp_tool_returns_tool_result_payload(monkeypatch):
    calls = []

    def fake_execute(tool_name, args):
        calls.append((tool_name, args))
        return FakeResult({"ok": True, "data": {"value": "ok"}, "summary": "tool completed", "error": "", "error_code": "", "truncated": False, "truncated_from": 0})

    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(fake_execute))

    payload = mcp_tools.call_mcp_tool("mypaper_get_current_time", {"timezone": "Asia/Shanghai"})

    assert calls == [("get_current_time", {"timezone": "Asia/Shanghai"})]
    assert payload["ok"] is True
    assert payload["data"] == {"value": "ok"}
    assert payload["summary"] == "tool completed"
    assert payload["error"] == ""
    assert payload["error_code"] == ""


def test_mcp_tool_registry_defines_public_tool_metadata():
    registry = mcp_tools.MCP_TOOL_REGISTRY

    assert set(registry) == {
        "mypaper_retrieve_knowledge",
        "mypaper_web_search",
        "mypaper_get_current_time",
    }
    web_search = registry["mypaper_web_search"]
    assert web_search["internal_tool_name"] == "web_search"
    assert web_search["public"] is True
    assert "query" in web_search["required_args"]
    assert web_search["defaults"]["count"] == 5


def test_retrieve_knowledge_rejects_empty_query(monkeypatch):
    def should_not_execute(tool_name, args):
        raise AssertionError("tool should not execute for invalid args")

    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(should_not_execute))

    payload = mcp_tools.call_mcp_tool("mypaper_retrieve_knowledge", {"query": "   "})

    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_ARGS"
    assert "query" in payload["error"]


def test_web_search_rejects_count_outside_allowed_range(monkeypatch):
    def should_not_execute(tool_name, args):
        raise AssertionError("tool should not execute for invalid args")

    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(should_not_execute))

    too_low = mcp_tools.call_mcp_tool("mypaper_web_search", {"query": "agent", "count": 0})
    too_high = mcp_tools.call_mcp_tool("mypaper_web_search", {"query": "agent", "count": 11})

    assert too_low["ok"] is False
    assert too_low["error_code"] == "INVALID_ARGS"
    assert too_high["ok"] is False
    assert too_high["error_code"] == "INVALID_ARGS"


def test_unknown_mcp_tool_returns_unknown_tool(monkeypatch):
    def should_not_execute(tool_name, args):
        raise AssertionError("unknown tool should not execute")

    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(should_not_execute))

    payload = mcp_tools.call_mcp_tool("unknown_tool", {})

    assert payload["ok"] is False
    assert payload["error_code"] == "UNKNOWN_TOOL"


def test_tool_wrapper_exception_is_structured_failure(monkeypatch):
    def fake_execute(tool_name, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper(fake_execute))

    payload = mcp_tools.call_mcp_tool("mypaper_get_current_time", {})

    assert payload["ok"] is False
    assert payload["error_code"] == "TOOL_EXECUTION_ERROR"
    assert "boom" in payload["error"]

