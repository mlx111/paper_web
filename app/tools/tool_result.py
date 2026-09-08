"""
Unified ToolResult model — single consistent return format for all tools.

Replaces the 4 different error patterns (JSON ok/error, raw dict, tuple, raw string)
with one standard: ToolResult → .to_message_content() for ToolMessage serialization.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standardized tool execution result."""

    ok: bool
    data: Any = None
    error: str = ""
    error_code: str = ""  # TOOL_FAILED / INVALID_ARGS / NOT_FOUND / TIMEOUT / UNKNOWN_TOOL
    summary: str = ""  # 1-line summary for agent context / compression
    truncated: bool = False
    truncated_from: int = 0

    @classmethod
    def success(
        cls,
        data: Any,
        summary: str = "",
        truncated: bool = False,
        truncated_from: int = 0,
    ) -> "ToolResult":
        return cls(
            ok=True,
            data=data,
            summary=summary,
            truncated=truncated,
            truncated_from=truncated_from,
        )

    @classmethod
    def failure(cls, error: str, error_code: str = "TOOL_FAILED") -> "ToolResult":
        return cls(ok=False, error=error, error_code=error_code)

    def to_message_content(self) -> str:
        """Serialize as a JSON string for ToolMessage.content."""
        return json.dumps(self.model_dump(), ensure_ascii=False, default=str)

    def to_summary(self, tool_name: str = "") -> str:
        """Produce a 1-line summary suitable for tool output pruning."""
        prefix = f"[{tool_name}] " if tool_name else ""

        if not self.ok:
            return f"{prefix}FAILED [{self.error_code}] {self.error[:100]}"

        data_str = json.dumps(self.data, ensure_ascii=False, default=str) if self.data is not None else ""
        size = len(data_str)
        preview = data_str[:80].replace("\n", " ")

        status = "ok"
        if self.truncated:
            status = f"truncated from {self.truncated_from}"

        return f"{prefix}{status} | {size} chars | {preview}"

    @classmethod
    def from_raw(cls, raw: Any, tool_name: str = "") -> "ToolResult":
        """Normalize any raw tool output into a ToolResult."""
        if isinstance(raw, ToolResult):
            return raw
        if isinstance(raw, dict):
            if "ok" in raw:
                return cls(**raw)
            return cls.success(data=raw)
        if isinstance(raw, (tuple, list)):
            content = raw[0] if raw else ""
            return cls.success(data=content)
        if isinstance(raw, str):
            # Check if it looks like JSON
            stripped = raw.strip()
            if stripped.startswith("{"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        if "ok" in parsed:
                            return cls(**parsed)
                        return cls.success(data=parsed)
                except (json.JSONDecodeError, TypeError):
                    pass
            return cls.success(data=raw)
        return cls.success(data=str(raw))
