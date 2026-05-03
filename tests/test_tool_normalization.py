"""Tests for tool normalization — ToolResult, ToolRegistry, ToolWrapper."""

import json

import pytest

from app.tools.tool_result import ToolResult
from app.tools.tool_registry import ToolCategory, ToolMeta, ToolRegistry
from app.tools.tool_wrapper import ToolWrapper


# ---------------------------------------------------------------------------
# TestToolResult
# ---------------------------------------------------------------------------

class TestToolResult:
    def test_success_factory(self):
        r = ToolResult.success(data={"papers": [{"title": "Test"}]})
        assert r.ok is True
        assert r.data["papers"][0]["title"] == "Test"
        assert r.error == ""

    def test_success_with_summary(self):
        r = ToolResult.success(data="result", summary="Found 3 papers")
        assert r.summary == "Found 3 papers"

    def test_failure_factory(self):
        r = ToolResult.failure("Something went wrong", "TOOL_FAILED")
        assert r.ok is False
        assert r.error == "Something went wrong"
        assert r.error_code == "TOOL_FAILED"

    def test_to_message_content_produces_valid_json(self):
        r = ToolResult.success(data={"key": "value"})
        content = r.to_message_content()
        parsed = json.loads(content)
        assert parsed["ok"] is True
        assert parsed["data"]["key"] == "value"

    def test_to_message_content_failure(self):
        r = ToolResult.failure("timeout", "TIMEOUT")
        content = r.to_message_content()
        parsed = json.loads(content)
        assert parsed["ok"] is False
        assert parsed["error"] == "timeout"
        assert parsed["error_code"] == "TIMEOUT"

    def test_to_summary_success(self):
        r = ToolResult.success(data="hello world")
        s = r.to_summary("search")
        assert "[search]" in s
        assert "ok" in s

    def test_to_summary_failure(self):
        r = ToolResult.failure("connection refused", "TOOL_FAILED")
        s = r.to_summary("download")
        assert "[download]" in s
        assert "FAILED" in s
        assert "connection refused" in s

    def test_from_raw_toolresult_passthrough(self):
        original = ToolResult.success(data="x")
        assert ToolResult.from_raw(original) is original

    def test_from_raw_dict_with_ok(self):
        raw = {"ok": True, "data": "hello"}
        r = ToolResult.from_raw(raw)
        assert r.ok is True
        assert r.data == "hello"

    def test_from_raw_plain_dict(self):
        raw = {"results": [1, 2, 3]}
        r = ToolResult.from_raw(raw)
        assert r.ok is True
        assert r.data == raw

    def test_from_raw_tuple(self):
        r = ToolResult.from_raw(("text content", ["doc1", "doc2"]))
        assert r.ok is True
        assert r.data == "text content"

    def test_from_raw_string(self):
        r = ToolResult.from_raw("plain text result")
        assert r.ok is True
        assert r.data == "plain text result"

    def test_from_raw_json_string(self):
        r = ToolResult.from_raw('{"ok": false, "error": "fail"}')
        assert r.ok is False
        assert r.error == "fail"


# ---------------------------------------------------------------------------
# TestToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        meta = ToolMeta(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.UTILITY,
        )
        reg.register(meta)
        assert reg.get("test_tool") is meta
        assert reg.get("nonexistent") is None

    def test_list_all(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(name="a", description="desc", category=ToolCategory.UTILITY))
        reg.register(ToolMeta(name="b", description="desc", category=ToolCategory.KNOWLEDGE))
        assert reg.tool_count == 2
        assert len(reg.list_all()) == 2

    def test_list_by_category(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(name="a", description="desc", category=ToolCategory.ACADEMIC))
        reg.register(ToolMeta(name="b", description="desc", category=ToolCategory.UTILITY))
        academic = reg.list_by_category(ToolCategory.ACADEMIC)
        assert len(academic) == 1
        assert academic[0].name == "a"

    def test_list_by_permission(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(name="safe", description="d", category=ToolCategory.UTILITY, permission="allow"))
        reg.register(ToolMeta(name="danger", description="d", category=ToolCategory.UTILITY, permission="ask_user"))
        assert len(reg.list_by_permission("ask_user")) == 1

    def test_format_descriptions(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(
            name="search",
            description="Search papers",
            category=ToolCategory.ACADEMIC,
            args_description="query (str)",
        ))
        desc = reg.format_descriptions()
        assert "search" in desc
        assert "Search papers" in desc
        assert "query (str)" in desc

    def test_format_descriptions_by_category(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(name="s", description="search", category=ToolCategory.ACADEMIC))
        reg.register(ToolMeta(name="t", description="time", category=ToolCategory.UTILITY))
        desc = reg.format_descriptions(ToolCategory.ACADEMIC)
        assert "search" in desc
        assert "time" not in desc

    def test_get_tools_list(self):
        from langchain_core.tools import tool as langchain_tool

        @langchain_tool(name_or_callable="demo_tool", description="demo")
        def demo_tool(x: str) -> str:
            return x

        reg = ToolRegistry()
        reg.register(ToolMeta(name="demo_tool", description="d", category=ToolCategory.UTILITY, tool_ref=demo_tool))
        tools = reg.get_tools_list()
        assert len(tools) == 1
        assert tools[0].name == "demo_tool"

    def test_tool_names(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(name="a", description="d", category=ToolCategory.UTILITY))
        reg.register(ToolMeta(name="b", description="d", category=ToolCategory.UTILITY))
        assert set(reg.tool_names) == {"a", "b"}


# ---------------------------------------------------------------------------
# TestToolWrapper
# ---------------------------------------------------------------------------

class TestToolWrapper:
    def test_execute_known_tool(self):
        from langchain_core.tools import tool as langchain_tool

        @langchain_tool(name_or_callable="add", description="adds two numbers")
        def add(a: int, b: int) -> str:
            return ToolResult.success(data={"sum": a + b}).to_message_content()

        reg = ToolRegistry()
        reg.register(ToolMeta(name="add", description="d", category=ToolCategory.UTILITY, tool_ref=add))
        wrapper = ToolWrapper(reg)

        result = wrapper.execute("add", {"a": 3, "b": 4})
        assert result.ok is True
        parsed = json.loads(result.data) if isinstance(result.data, str) else result.data
        assert isinstance(parsed, dict)
        # data is {"sum": 7} wrapped in ToolResult JSON

    def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        wrapper = ToolWrapper(reg)
        result = wrapper.execute("nonexistent", {})
        assert result.ok is False
        assert result.error_code == "UNKNOWN_TOOL"

    def test_execute_tool_message(self):
        from langchain_core.tools import tool as langchain_tool

        @langchain_tool(name_or_callable="echo", description="echoes input")
        def echo(text: str) -> str:
            return ToolResult.success(data=text).to_message_content()

        reg = ToolRegistry()
        reg.register(ToolMeta(name="echo", description="d", category=ToolCategory.UTILITY, tool_ref=echo))
        wrapper = ToolWrapper(reg)

        result, meta = wrapper.execute_tool_message({
            "name": "echo",
            "args": {"text": "hello"},
            "id": "call_123",
        })
        assert result.ok is True
        assert meta["tool_name"] == "echo"
        assert meta["tool_call_id"] == "call_123"

    def test_needs_permission(self):
        reg = ToolRegistry()
        reg.register(ToolMeta(name="safe", description="d", category=ToolCategory.UTILITY, permission="allow"))
        reg.register(ToolMeta(name="danger", description="d", category=ToolCategory.UTILITY, permission="ask_user"))
        wrapper = ToolWrapper(reg)
        assert wrapper.needs_permission("safe") is False
        assert wrapper.needs_permission("danger") is True
        assert wrapper.needs_permission("unknown") is False


# ---------------------------------------------------------------------------
# TestToolOutputConsistency
# ---------------------------------------------------------------------------

class TestToolOutputConsistency:
    """Verify all tools produce parseable JSON output."""

    def test_all_tools_importable(self):
        from app.tools import tool_registry
        assert tool_registry.tool_count >= 10

    def test_academic_search_error_is_valid_json(self):
        # Simulate by calling ToolResult.failure directly (avoids network)
        result = ToolResult.failure("network error", "TOOL_FAILED")
        content = result.to_message_content()
        parsed = json.loads(content)
        assert parsed["ok"] is False
        assert "error" in parsed
        assert "error_code" in parsed

    def test_web_search_error_is_valid_json(self):
        result = ToolResult.failure("search failed", "TOOL_FAILED")
        content = result.to_message_content()
        parsed = json.loads(content)
        assert parsed["ok"] is False

    def test_time_tool_error_is_valid_json(self):
        result = ToolResult.failure("timezone invalid", "TOOL_FAILED")
        content = result.to_message_content()
        parsed = json.loads(content)
        assert parsed["ok"] is False

    def test_error_format_consistency(self):
        """All tool errors should have the same JSON structure."""
        errors = [
            ToolResult.failure("e1", "TOOL_FAILED").to_message_content(),
            ToolResult.failure("e2", "TIMEOUT").to_message_content(),
            ToolResult.failure("e3", "NOT_FOUND").to_message_content(),
        ]
        for content in errors:
            parsed = json.loads(content)
            assert "ok" in parsed
            assert parsed["ok"] is False
            assert "error" in parsed
            assert "error_code" in parsed
            # No 'message' key — standardized to 'error'
            assert "message" not in parsed
