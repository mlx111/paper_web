"""HITL manager — orchestrates human-in-the-loop approval flow.

When a high-risk tool is called, the manager creates a pending approval,
returns a 'pending' result to the agent, and waits for human decision.
After approval, the tool is actually executed; after rejection, a
failure result is returned.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from ..tool_result import ToolResult
from .pending_store import PendingStore, pending_store


class HITLManager:
    """Manages the human-in-the-loop approval lifecycle."""

    def __init__(self, store: PendingStore | None = None, timeout: int = 300):
        self.store = store or pending_store
        self.timeout = timeout

    def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        session_id: str,
        question: str = "",
    ) -> ToolResult:
        """Create a pending approval and return a 'pending' ToolResult.

        The agent sees this result and can inform the user that approval
        is needed.
        """
        approval = self.store.create(
            tool_name=tool_name,
            args=args,
            session_id=session_id,
            question=question,
            expires_in=self.timeout,
        )
        logger.info(
            "HITL: pending approval created for {} (id={}, session={})",
            tool_name, approval.approval_id, session_id,
        )
        return ToolResult.success(
            data={
                "approval_id": approval.approval_id,
                "pending": True,
                "tool_name": tool_name,
                "args": args,
                "message": f"Tool '{tool_name}' requires human approval. "
                           f"Approval ID: {approval.approval_id}. "
                           f"Please approve or reject via the HITL API.",
            },
            summary=f"[{tool_name}] awaiting human approval (id={approval.approval_id})",
        )

    async def approve_and_execute(
        self,
        approval_id: str,
        decided_by: str = "",
        reason: str = "",
        execute_fn: Any = None,
    ) -> ToolResult:
        """Approve a pending request and execute the tool.

        Args:
            approval_id: The approval to approve.
            decided_by: Who approved it.
            reason: Optional reason.
            execute_fn: A callable that takes args dict and returns ToolResult.
        """
        approval = self.store.get(approval_id)
        if approval is None:
            return ToolResult.failure(
                f"Approval {approval_id} not found", "APPROVAL_NOT_FOUND"
            )
        if approval.status != "pending":
            return ToolResult.failure(
                f"Approval {approval_id} is already {approval.status}",
                "APPROVAL_ALREADY_RESOLVED",
            )

        # Mark as approved
        self.store.update(approval_id, "approved", decided_by, reason)

        if execute_fn is None:
            # No execution function provided — just mark as approved
            result = ToolResult.success(
                data={"approved": True, "tool_name": approval.tool_name},
                summary=f"[{approval.tool_name}] approved and executed",
            )
        else:
            try:
                raw = execute_fn(approval.args)
                if asyncio.iscoroutine(raw):
                    raw = await raw
                result = ToolResult.from_raw(raw, approval.tool_name)
                if not result.summary:
                    result.summary = result.to_summary(approval.tool_name)
            except Exception as exc:
                logger.error("HITL: execution failed for {}: {}", approval.tool_name, exc)
                result = ToolResult.failure(str(exc), "TOOL_EXECUTION_ERROR")

        # Store the result
        self.store.update(approval_id, "approved", decided_by, reason, result)
        return result

    def reject(
        self,
        approval_id: str,
        decided_by: str = "",
        reason: str = "",
    ) -> ToolResult:
        """Reject a pending request."""
        approval = self.store.get(approval_id)
        if approval is None:
            return ToolResult.failure(
                f"Approval {approval_id} not found", "APPROVAL_NOT_FOUND"
            )
        if approval.status != "pending":
            return ToolResult.failure(
                f"Approval {approval_id} is already {approval.status}",
                "APPROVAL_ALREADY_RESOLVED",
            )

        result = ToolResult.failure(
            f"Tool '{approval.tool_name}' was rejected by user: {reason}",
            "REJECTED",
        )
        self.store.update(approval_id, "rejected", decided_by, reason, result)
        return result

    async def wait_for_approval(
        self,
        approval_id: str,
        timeout: int | None = None,
    ) -> ToolResult:
        """Poll for approval status until resolved or timeout."""
        timeout = timeout or self.timeout
        elapsed = 0.0
        interval = 0.5

        while elapsed < timeout:
            approval = self.store.get(approval_id)
            if approval is None:
                return ToolResult.failure(
                    f"Approval {approval_id} not found", "APPROVAL_NOT_FOUND"
                )
            if approval.status == "approved" and approval.result:
                return approval.result
            if approval.status == "rejected" and approval.result:
                return approval.result
            if approval.status == "expired":
                return ToolResult.failure(
                    f"Approval {approval_id} expired", "APPROVAL_TIMEOUT"
                )
            await asyncio.sleep(interval)
            elapsed += interval

        return ToolResult.failure(
            f"Approval {approval_id} timed out after {timeout}s",
            "APPROVAL_TIMEOUT",
        )


# Singleton
hitl_manager = HITLManager()
