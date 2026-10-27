"""HITL router — API endpoints for human-in-the-loop tool approval.

Endpoints:
    GET    /api/hitl/pending            — list pending approvals
    POST   /api/hitl/propose             — external: create a pending approval (L3 Self-Healing)
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


class ProposeRequest(BaseModel):
    """L3 Self-Healing 外部提议修复动作的请求体。

    L3 agent（运行在 llmops 侧）通过此端点把高风险修复提议写入 pending_store，
    等待人工通过 approve/reject 端点处理。approve 时因 tool_name 不在本地 registry，
    execute_fn=None，hitl_manager 仅标记为 approved（不真正执行 tool），由人工后续手动处理。
    """

    tool_name: str  # 如 "external_fix_proposal" / "rebuild_index" / "update_prompt"
    args: dict = {}
    session_id: str = "self-heal"
    question: str = ""


@router.post("/propose")
async def propose(req: ProposeRequest):
    """外部创建一个 pending approval（L3 Self-Healing 提议高风险修复用）。

    与 agent 内部调高风险 tool 触发 request_approval 的路径不同，此端点供跨服务
    （llmops L3 agent）调用：把修复提议记入 pending_store，返回 approval_id 供人工审批。
    """
    approval = pending_store.create(
        tool_name=req.tool_name,
        args=dict(req.args),
        session_id=req.session_id,
        question=req.question,
    )
    return {
        "ok": True,
        "approval_id": approval.approval_id,
        "status": "pending",
        "tool_name": approval.tool_name,
        "session_id": approval.session_id,
        "created_at": approval.created_at,
    }


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
