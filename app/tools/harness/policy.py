"""Tool policy — authorization control for tool calls.

Provides per-session tool allow/block lists so the harness can reject
unauthorized tool invocations before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolPolicy:
    """Authorization policy for tool invocation."""

    allowed_tools: set[str] | None = None  # None = allow all
    blocked_tools: set[str] = field(default_factory=set)
    high_risk_tools: set[str] = field(default_factory=set)
    session_overrides: dict[str, "ToolPolicy"] = field(default_factory=dict)

    def is_authorized(self, tool_name: str, session_id: str = "") -> bool:
        """Check whether *tool_name* is authorized for *session_id*."""
        policy = self.session_overrides.get(session_id, self)
        if tool_name in policy.blocked_tools:
            return False
        if policy.allowed_tools is not None and tool_name not in policy.allowed_tools:
            return False
        return True


# Default policy: all tools allowed, send_email marked as high-risk
default_policy = ToolPolicy(
    high_risk_tools={"send_email"},
)
