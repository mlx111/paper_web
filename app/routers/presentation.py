import json

from fastapi import APIRouter, HTTPException
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from agents.presentation_workflow_service import presentation_workflow_service
from models.request import ClearRequest, PresentationRequest
from models.response import ApiResponse, SessionInfoResponse


router = APIRouter(prefix="/presentation", tags=["presentation"])


@router.post("/chat")
async def chat(request: PresentationRequest):
    try:
        result = presentation_workflow_service.run_topic(
            request.session_id,
            request.topic,
            request.target_pages,
        )
        return {"code": 200, "message": "success", "data": result}
    except Exception as exc:
        logger.error("[presentation {}] chat failed: {}", request.session_id, exc)
        return {
            "code": 500,
            "message": "error",
            "data": {"success": False, "answer": None, "errorMessage": str(exc)},
        }


@router.post("/chat_stream")
async def chat_stream(request: PresentationRequest):
    async def event_generator():
        try:
            async for chunk in presentation_workflow_service.query_stream(request):
                chunk_type = chunk.get("type", "unknown")
                chunk_data = chunk.get("data")
                payload = {"type": "done", "data": chunk_data} if chunk_type == "complete" else {"type": chunk_type, "data": chunk_data}
                yield {"event": "message", "data": json.dumps(payload, ensure_ascii=False)}
        except Exception as exc:
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@router.post("/clear", response_model=ApiResponse)
async def clear_session(request: ClearRequest):
    try:
        success = presentation_workflow_service.clear_session(request.session_id)
        return ApiResponse(
            status="success" if success else "error",
            message="演示会话已清空" if success else "清空演示会话失败",
            data=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    try:
        history = presentation_workflow_service.get_session_history(session_id)
        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(history),
            history=history,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
