"""
ToolWrapper — standardized execution layer for all tools.

Ensures every tool invocation returns a consistent ToolResult,
regardless of the underlying tool's raw return type.
"""

from __future__ import annotations

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

    def needs_permission(self, tool_name: str) -> bool:
        """Check if a tool requires user approval before execution."""
        meta = self.registry.get(tool_name)
        if meta is None:
            return False
        return meta.permission == "ask_user"
