from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.run_trace_service import default_run_trace_service


router = APIRouter(prefix="/traces", tags=["traces"])
trace_service = default_run_trace_service


@router.get("")
async def list_traces(session_id: str | None = None):
    runs = trace_service.list_runs(session_id=session_id)
    return {
        "code": 200,
        "message": "success",
        "data": {
            "count": len(runs),
            "runs": runs,
        },
    }


@router.get("/{run_id}")
async def get_trace(run_id: str):
    try:
        trace = trace_service.load_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trace not found: {run_id}")

    return {
        "code": 200,
        "message": "success",
        "data": trace,
    }


@router.get("/{run_id}/summary")
async def get_trace_summary(run_id: str):
    try:
        summary = trace_service.summarize_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trace not found: {run_id}")

    return {
        "code": 200,
        "message": "success",
        "data": summary,
    }


@router.get("/{run_id}/replay")
async def get_trace_replay(run_id: str):
    try:
        replay = trace_service.build_replay(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trace not found: {run_id}")

    return {
        "code": 200,
        "message": "success",
        "data": replay,
    }
