"""
ToolWrapper — standardized execution layer for all tools.

Ensures every tool invocation returns a consistent ToolResult,
regardless of the underlying tool's raw return type.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from .tool_registry import ToolRegistry
from .tool_result import ToolResult


class ToolWrapper:
    """Wraps tool execution to standardize inputs and outputs."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name and return a normalized ToolResult.

        Handles: unknown tools, execution errors, and raw-output normalization.
        """
        meta = self.registry.get(tool_name)
        if meta is None or meta.tool_ref is None:
            logger.warning("ToolWrapper: unknown tool requested — {}", tool_name)
            return ToolResult.failure(
                f"Unknown tool: {tool_name}",
                "UNKNOWN_TOOL",
            )

        try:
            raw = meta.tool_ref.invoke(args)
        except Exception as exc:
            logger.error("ToolWrapper: {} execution failed — {}", tool_name, exc)
            return ToolResult.failure(str(exc), "TOOL_EXECUTION_ERROR")

        result = ToolResult.from_raw(raw, tool_name)

        # Auto-generate summary if not already set
        if not result.summary:
            result.summary = result.to_summary(tool_name)

        return result

    def execute_with_trace(
        self,
        tool_name: str,
        args: dict[str, Any],
        trace_service: Any = None,
        run_id: str = "",
        parent_step_id: str | None = None,
        node_name: str = "",
    ) -> ToolResult:
        """Execute a tool and record a tool-level run trace step when available."""
        if trace_service is None or not run_id:
            return self.execute(tool_name, args)

        with trace_service.step(run_id, f"tool:{tool_name}", "tool", parent_step_id=parent_step_id) as trace_step:
            trace_step.set_input({
                "tool_name": tool_name,
                "arguments": self._redact_sensitive(args or {}),
                "node_name": node_name,
            })

            result = self.execute(tool_name, args)
            output = self._trace_output(tool_name, result)
            trace_step.set_output(output)
            if not result.ok:
                trace_step.mark_failed(result.error or result.error_code or "tool failed")
            return result

    def execute_tool_message(self, tool_call: dict[str, Any]) -> tuple[ToolResult, dict]:
        """
        Convenience for processing a tool_call dict (name + args + id).
        Returns (ToolResult, call_metadata).
        """
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        call_id = tool_call.get("id", "")

        result = self.execute(tool_name, tool_args)

        meta = {
            "tool_name": tool_name,
            "tool_call_id": call_id,
            "ok": result.ok,
        }

        return result, meta

    def execute_tool_message_with_trace(
        self,
        tool_call: dict[str, Any],
        trace_service: Any = None,
        run_id: str = "",
        parent_step_id: str | None = None,
        node_name: str = "",
    ) -> tuple[ToolResult, dict]:
        """Trace-aware version of execute_tool_message."""
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        call_id = tool_call.get("id", "")

        result = self.execute_with_trace(
            tool_name,
            tool_args,
            trace_service=trace_service,
            run_id=run_id,
            parent_step_id=parent_step_id,
            node_name=node_name,
        )

        meta = {
            "tool_name": tool_name,
            "tool_call_id": call_id,
            "ok": result.ok,
        }

        return result, meta

    def needs_permission(self, tool_name: str) -> bool:
        """Check if a tool requires user approval before execution."""
        meta = self.registry.get(tool_name)
        if meta is None:
            return False
        return meta.permission == "ask_user"

    @staticmethod
    def _redact_sensitive(value: Any) -> Any:
        sensitive_keys = ("api_key", "apikey", "token", "password", "secret", "authorization")
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                if any(pattern in str(key).lower() for pattern in sensitive_keys):
                    redacted[key] = "***"
                else:
                    redacted[key] = ToolWrapper._redact_sensitive(item)
            return redacted
        if isinstance(value, list):
            return [ToolWrapper._redact_sensitive(item) for item in value]
        return value

    @staticmethod
    def _json_size(value: Any) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False, default=str))
        except TypeError:
            return len(str(value))

    @classmethod
    def _trace_output(cls, tool_name: str, result: ToolResult) -> dict[str, Any]:
        summary = result.summary or result.to_summary(tool_name)
        return {
            "ok": result.ok,
            "summary": summary,
            "error": result.error,
            "error_code": result.error_code,
            "data_size": cls._json_size(result.data),
            "truncated": result.truncated,
            "truncated_from": result.truncated_from,
        }
