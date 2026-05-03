"""YAML Workflow Engine routes with checkpoint support."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from models.request import WorkflowRunRequest, WorkflowProgressRequest, ClearRequest
from services.workflow_loader import WorkflowLoader
from services.workflow_engine import WorkflowEngine
from services.checkpoint_store import CheckpointStore
from services.checkpoint_manager import CheckpointManager

router = APIRouter(prefix="/workflow", tags=["workflow"])

_loader = WorkflowLoader()
_engine = WorkflowEngine()
_store = CheckpointStore()
checkpoint_manager = CheckpointManager(engine=_engine, store=_store)


# ---------------------------------------------------------------------------
# GET /workflow/list
# ---------------------------------------------------------------------------

@router.get("/list")
async def list_workflows():
    """List all available YAML workflow names."""
    try:
        names = sorted(
            p.stem for p in _loader.workflows_dir.glob("*.yaml")
            if p.is_file()
        )
        return {
            "code": 200,
            "message": "success",
            "data": {"workflows": names, "count": len(names)},
        }
    except Exception as exc:
        logger.error("list_workflows failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /workflow/run
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_workflow(request: WorkflowRunRequest):
    """Execute a YAML workflow synchronously with checkpoint auto-resume."""
    try:
        wf = _loader.load(request.workflow_name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow not found: {request.workflow_name}",
        )
    except Exception as exc:
        logger.error("Failed to load workflow '{}': {}", request.workflow_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        result = await checkpoint_manager.run(wf, session_id=request.session_id, params=request.params)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "session_id": request.session_id,
                "workflow_name": request.workflow_name,
                "output": result,
            },
        }
    except Exception as exc:
        logger.error("Workflow '{}' execution failed: {}", request.workflow_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /workflow/run_stream
# ---------------------------------------------------------------------------

@router.post("/run_stream")
async def run_workflow_stream(request: WorkflowRunRequest):
    """Execute a YAML workflow with SSE streaming and checkpoint support."""
    try:
        _loader.load(request.workflow_name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow not found: {request.workflow_name}",
        )

    async def event_generator():
        wf = _loader.load(request.workflow_name)
        async for ev in checkpoint_manager.run_stream(
            wf, session_id=request.session_id, params=request.params
        ):
            yield {"event": ev.get("type", "message"), "data": json.dumps(ev, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# POST /workflow/progress
# ---------------------------------------------------------------------------

@router.post("/progress")
async def workflow_progress(request: WorkflowProgressRequest):
    """Query checkpoint progress for a session's workflow."""
    try:
        progress = checkpoint_manager.get_progress(request.session_id, request.workflow_name)
        return {
            "code": 200,
            "message": "success",
            "data": progress,
        }
    except Exception as exc:
        logger.error("workflow_progress failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /workflow/clear
# ---------------------------------------------------------------------------

@router.post("/clear")
async def clear_workflow(request: ClearRequest):
    """Clear all checkpoints for a session."""
    try:
        checkpoint_manager.clear(request.session_id)
        return {
            "code": 200,
            "message": "Checkpoints cleared",
            "data": {"session_id": request.session_id},
        }
    except Exception as exc:
        logger.error("clear_workflow failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))
