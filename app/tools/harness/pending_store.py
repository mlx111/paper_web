"""Pending store — in-memory store for HITL approval requests.

When a high-risk tool (permission="ask_user") is called, the harness
creates a pending approval entry and returns it to the agent. The
approval can be resolved via the HITL API endpoints.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..tool_result import ToolResult


@dataclass
class PendingApproval:
    """A pending human-in-the-loop approval request."""

    approval_id: str
    tool_name: str
    args: dict[str, Any]
    session_id: str
    question: str
    created_at: float
    status: str = "pending"  # pending / approved / rejected / expired
    decided_by: str = ""
    decision_reason: str = ""
    result: ToolResult | None = None
    expires_in: int = 300  # 5 minutes


class PendingStore:
    """In-memory store for pending approvals."""

    def __init__(self):
        self._store: dict[str, PendingApproval] = {}

    def create(
        self,
        tool_name: str,
        args: dict[str, Any],
        session_id: str,
        question: str = "",
        expires_in: int = 300,
    ) -> PendingApproval:
        """Create a new pending approval and return it."""
        approval = PendingApproval(
            approval_id=uuid.uuid4().hex[:12],
            tool_name=tool_name,
            args=dict(args),
            session_id=session_id,
            question=question,
            created_at=time.time(),
            expires_in=expires_in,
        )
        self._store[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> PendingApproval | None:
        """Get a pending approval by ID."""
        approval = self._store.get(approval_id)
        if approval is None:
            return None
        # Check expiry
        if approval.status == "pending":
            if time.time() - approval.created_at > approval.expires_in:
                approval.status = "expired"
        return approval

    def list_pending(self, session_id: str | None = None) -> list[PendingApproval]:
        """List all pending approvals, optionally filtered by session."""
        result = []
        for approval in self._store.values():
            if approval.status != "pending":
                continue
            # Check expiry
            if time.time() - approval.created_at > approval.expires_in:
                approval.status = "expired"
                continue
            if session_id and approval.session_id != session_id:
                continue
            result.append(approval)
        return result

    def update(
        self,
        approval_id: str,
        status: str,
        decided_by: str = "",
        reason: str = "",
        result: ToolResult | None = None,
    ) -> PendingApproval | None:
        """Update an approval's status."""
        approval = self._store.get(approval_id)
        if approval is None:
            return None
        approval.status = status
        approval.decided_by = decided_by
        approval.decision_reason = reason
        if result is not None:
            approval.result = result
        return approval

    def cleanup_expired(self) -> int:
        """Remove expired approvals. Returns count removed."""
        now = time.time()
        expired_ids = [
            aid for aid, a in self._store.items()
            if now - a.created_at > a.expires_in and a.status == "pending"
        ]
        for aid in expired_ids:
            self._store[aid].status = "expired"
        return len(expired_ids)


# Singleton
pending_store = PendingStore()
