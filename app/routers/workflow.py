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
from services.run_trace_service import default_run_trace_service

router = APIRouter(prefix="/workflow", tags=["workflow"])

_loader = WorkflowLoader()
_store = CheckpointStore()


def _new_checkpoint_manager() -> tuple[WorkflowEngine, CheckpointManager]:
    engine = WorkflowEngine()
    return engine, CheckpointManager(engine=engine, store=_store)


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
        engine, manager = _new_checkpoint_manager()
        trace_run = default_run_trace_service.start_run(
            session_id=request.session_id,
            route=f"workflow:{request.workflow_name}",
            question=str(request.params.get("question", "")),
            metadata={"workflow_name": request.workflow_name},
        )
        engine.trace_service = default_run_trace_service
        engine.trace_run_id = trace_run.run_id
        result = await manager.run(wf, session_id=request.session_id, params=request.params)
        default_run_trace_service.end_run(trace_run.run_id, status="completed")
        return {
            "code": 200,
            "message": "success",
            "data": {
                "session_id": request.session_id,
                "workflow_name": request.workflow_name,
                "run_id": trace_run.run_id,
                "trace_path": str(trace_run.trace_path),
                "output": result,
            },
        }
    except Exception as exc:
        if "trace_run" in locals():
            default_run_trace_service.end_run(trace_run.run_id, status="failed", error=str(exc))
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
        engine, manager = _new_checkpoint_manager()
        trace_run = default_run_trace_service.start_run(
            session_id=request.session_id,
            route=f"workflow:{request.workflow_name}",
            question=str(request.params.get("question", "")),
            metadata={"workflow_name": request.workflow_name},
        )
        engine.trace_service = default_run_trace_service
        engine.trace_run_id = trace_run.run_id
        final_status = "completed"
        final_error = None
        try:
            async for ev in manager.run_stream(
                wf, session_id=request.session_id, params=request.params
            ):
                if ev.get("type") == "start":
                    ev = {
                        **ev,
                        "run_id": trace_run.run_id,
                        "trace_path": str(trace_run.trace_path),
                    }
                if ev.get("type") == "step_error":
                    final_status = "failed"
                    final_error = ev.get("error")
                yield {"event": ev.get("type", "message"), "data": json.dumps(ev, ensure_ascii=False)}
        except Exception as exc:
            final_status = "failed"
            final_error = str(exc)
            raise
        finally:
            default_run_trace_service.end_run(trace_run.run_id, status=final_status, error=final_error)

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# POST /workflow/progress
# ---------------------------------------------------------------------------

@router.post("/progress")
async def workflow_progress(request: WorkflowProgressRequest):
    """Query checkpoint progress for a session's workflow."""
    try:
        _, manager = _new_checkpoint_manager()
        progress = manager.get_progress(request.session_id, request.workflow_name)
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
        _, manager = _new_checkpoint_manager()
        manager.clear(request.session_id)
        return {
            "code": 200,
            "message": "Checkpoints cleared",
            "data": {"session_id": request.session_id},
        }
    except Exception as exc:
        logger.error("clear_workflow failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))
