"""Research module API routes.

This router exposes an isolated entry point for the scientific research workflow.
It keeps the research session history separate from the chat/file modules.
"""

import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from agents.research_workflow_service import research_workflow_service
from models.request import ChatRequest, ClearRequest
from models.response import ApiResponse, SessionInfoResponse


router = APIRouter(prefix="/research", tags=["research"])


@router.post("/chat")
async def chat(request: ChatRequest):
    """Non-streaming research entry point."""
    try:
        logger.info(f"[research {request.id}] received chat request: {request.question}")
        answer = await research_workflow_service.query(
            request.question,
            session_id=request.id,
        )

        return {
            "code": 200,
            "message": "success",
            "data": {
                "success": True,
                "answer": answer,
                "errorMessage": None,
            },
        }
    except Exception as exc:
        logger.error(f"[research {request.id}] chat failed: {exc}")
        return {
            "code": 500,
            "message": "error",
            "data": {
                "success": False,
                "answer": None,
                "errorMessage": str(exc),
            },
        }


@router.post("/chat_stream")
async def chat_stream(request: ChatRequest):
    """Streaming research entry point."""
    logger.info(f"[research {request.id}] received streaming request: {request.question}")

    async def event_generator():
        try:
            async for chunk in research_workflow_service.query_stream(request.question, session_id=request.id):
                chunk_type = chunk.get("type", "unknown")
                chunk_data = chunk.get("data", None)

                if chunk_type == "debug":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "debug",
                                "node": chunk.get("node", "unknown"),
                                "message_type": chunk.get("message_type", "unknown"),
                                "data": chunk_data,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "tool_call":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "tool_call",
                                "node": chunk.get("node", "unknown"),
                                "data": chunk_data,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "search_results":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "search_results",
                                "node": chunk.get("node", "unknown"),
                                "data": chunk_data,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "content":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "content",
                                "node": chunk.get("node", "unknown"),
                                "data": chunk_data,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "complete":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "done",
                                "data": chunk_data,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "error":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "error",
                                "data": str(chunk_data),
                            },
                            ensure_ascii=False,
                        ),
                    }

            logger.info(f"[research {request.id}] streaming complete")
        except Exception as exc:
            logger.error(f"[research {request.id}] streaming failed: {exc}")
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "error",
                        "data": str(exc),
                    },
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(event_generator())


@router.post("/clear", response_model=ApiResponse)
async def clear_session(request: ClearRequest):
    """Clear research-session history only."""
    try:
        success = research_workflow_service.clear_session(request.session_id)
        logger.info(f"[research {request.session_id}] clear session result: {success}")

        return ApiResponse(
            status="success" if success else "error",
            message="研究会话已清空" if success else "清空研究会话失败",
            data=None,
        )
    except Exception as exc:
        logger.error(f"[research {request.session_id}] clear failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    """Return the isolated research history for one session."""
    try:
        history = research_workflow_service.get_session_history(session_id)
        artifacts = research_workflow_service._summarize_research_artifacts(session_id)
        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(history),
            history=history,
            artifacts=artifacts,
        )
    except Exception as exc:
        logger.error(f"[research {session_id}] get_session_info failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/report/regenerate", response_model=ApiResponse)
async def regenerate_report(request: ClearRequest):
    """Regenerate the research report from saved artifacts."""
    try:
        artifacts = research_workflow_service.regenerate_report(request.session_id)
        return ApiResponse(
            status="success",
            message="研究报告已重新生成",
            data=artifacts,
        )
    except Exception as exc:
        logger.error(f"[research {request.session_id}] regenerate report failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
