"""HITL router — API endpoints for human-in-the-loop tool approval.

Endpoints:
    GET    /api/hitl/pending            — list pending approvals
    POST   /api/hitl/{id}/approve       — approve and execute
    POST   /api/hitl/{id}/reject        — reject
    GET    /api/hitl/{id}/result        — query approval result
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from tools.harness.pending_store import pending_store
from tools.harness.hitl_manager import hitl_manager

router = APIRouter(prefix="/api/hitl", tags=["hitl"])


class ApproveRequest(BaseModel):
    decided_by: str = "user"
    reason: str = ""


class RejectRequest(BaseModel):
    decided_by: str = "user"
    reason: str = ""


@router.get("/pending")
async def list_pending(session_id: str | None = None):
    """List all pending approvals, optionally filtered by session."""
    items = pending_store.list_pending(session_id=session_id)
    return {
        "count": len(items),
        "items": [
            {
                "approval_id": a.approval_id,
                "tool_name": a.tool_name,
                "args": a.args,
                "session_id": a.session_id,
                "question": a.question,
                "created_at": a.created_at,
                "status": a.status,
            }
            for a in items
        ],
    }


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, req: ApproveRequest):
    """Approve a pending tool call and execute it."""
    # Resolve the tool and its execute function
    approval = pending_store.get(approval_id)
    if approval is None:
        return {"ok": False, "error": f"Approval {approval_id} not found"}

    # Get the tool's underlying invoke function
    from tools.registry_factory import build_tool_registry
    registry = build_tool_registry()
    meta = registry.get(approval.tool_name)

    execute_fn = None
    if meta and meta.tool_ref:
        execute_fn = lambda args: meta.tool_ref.invoke(args)

    result = await hitl_manager.approve_and_execute(
        approval_id,
        decided_by=req.decided_by,
        reason=req.reason,
        execute_fn=execute_fn,
    )

    return {
        "ok": result.ok,
        "approval_id": approval_id,
        "status": "approved",
        "result": result.to_message_content(),
    }


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, req: RejectRequest):
    """Reject a pending tool call."""
    result = hitl_manager.reject(
        approval_id,
        decided_by=req.decided_by,
        reason=req.reason,
    )
    return {
        "ok": result.ok,
        "approval_id": approval_id,
        "status": "rejected",
        "result": result.to_message_content(),
    }


@router.get("/{approval_id}/result")
async def get_result(approval_id: str):
    """Query the result of a resolved approval."""
    approval = pending_store.get(approval_id)
    if approval is None:
        return {"ok": False, "error": f"Approval {approval_id} not found"}
    return {
        "ok": True,
        "approval_id": approval_id,
        "tool_name": approval.tool_name,
        "status": approval.status,
        "decided_by": approval.decided_by,
        "decision_reason": approval.decision_reason,
        "result": approval.result.to_message_content() if approval.result else None,
    }
