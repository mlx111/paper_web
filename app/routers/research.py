"""Research module API routes.

This router exposes an isolated entry point for the scientific research workflow.
It keeps the research session history separate from the chat/file modules.
"""

import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from agents.research_workflow_service import research_workflow_service
from models.request import ChatRequest, ClearRequest, ConfirmCandidateRequest
from models.response import SessionInfoResponse


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

                if chunk_type == "stage":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "stage",
                                "stage": chunk.get("stage", ""),
                                "status": chunk.get("status", ""),
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "candidates":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "candidates",
                                "data": chunk_data,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif chunk_type == "debug":
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


@router.post("/clear")
async def clear_session(request: ClearRequest):
    """Clear research-session history only."""
    try:
        success = research_workflow_service.clear_session(request.session_id)
        logger.info(f"[research {request.session_id}] clear session result: {success}")

        return {
            "code": 200 if success else 500,
            "message": "研究会话已清空" if success else "清空研究会话失败",
            "data": None,
        }
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


@router.post("/report/regenerate")
async def regenerate_report(request: ClearRequest):
    """Regenerate the research report from saved artifacts."""
    try:
        artifacts = research_workflow_service.regenerate_report(request.session_id)
        return {
            "code": 200,
            "message": "研究报告已重新生成",
            "data": artifacts,
        }
    except Exception as exc:
        logger.error(f"[research {request.session_id}] regenerate report failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/report/quality")
async def check_report_quality(request: ClearRequest):
    """Check the quality of a completed research report."""
    try:
        report = research_workflow_service.check_report_quality(request.session_id)
        return {
            "code": 200,
            "message": "研究报告质量检查完成",
            "data": report,
        }
    except Exception as exc:
        logger.error(f"[research {request.session_id}] quality check failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/candidates")
async def get_research_candidates(request: ChatRequest):
    """Phase 1: Get research candidates without running full research."""
    logger.info(f"[research {request.id}] get candidates: {request.question}")

    async def event_generator():
        try:
            async for chunk in research_workflow_service.get_candidates(request.question, session_id=request.id):
                chunk_type = chunk.get("type", "unknown")
                chunk_data = chunk.get("data", None)

                if chunk_type == "candidates":
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "candidates",
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
        except Exception as exc:
            logger.error(f"[research {request.id}] get_candidates failed: {exc}")
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


@router.post("/confirm_candidate")
async def confirm_candidate(request: ConfirmCandidateRequest):
    """Phase 1.5: User confirms a research candidate."""
    try:
        logger.info(f"[research {request.session_id}] confirm candidate: {request.candidate_id}")
        pending = research_workflow_service._load_clarification_state(request.session_id)
        if not pending or pending.get("status") != "awaiting_selection":
            return {
                "code": 400,
                "message": "没有待确认的候选方案",
                "data": None,
            }

        candidates = list(pending.get("candidates") or [])
        selected = None
        for c in candidates:
            if c.get("candidate_id") == request.candidate_id:
                selected = c
                break

        if not selected:
            return {
                "code": 400,
                "message": f"未找到候选方案 {request.candidate_id}",
                "data": None,
            }

        modified_query = (request.modified_query or "").strip()
        if modified_query:
            refined_query = modified_query
        else:
            refined_query = str(selected.get("search_keywords") or pending.get("refined_query") or "")

        research_workflow_service._save_clarification_state(request.session_id, {
            "status": "confirmed",
            "question": str(pending.get("question") or ""),
            "candidates": candidates,
            "selected_candidate_id": request.candidate_id,
            "refined_query": refined_query,
            "clarification_summary": str(pending.get("clarification_summary") or ""),
        })

        return {
            "code": 200,
            "message": "success",
            "data": {
                "candidate_id": request.candidate_id,
                "refined_query": refined_query,
                "title": str(selected.get("title") or ""),
            },
        }
    except Exception as exc:
        logger.error(f"[research {request.session_id}] confirm_candidate failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prepare_rerun")
async def prepare_research_rerun(request: ClearRequest):
    """Restore clarification state so the next query_stream skips clarification and re-runs the full research."""
    try:
        artifacts = research_workflow_service._load_research_artifacts(request.session_id)
        manifest = artifacts.get("manifest") or {}
        clarification = artifacts.get("clarification") or {}
        question = str(manifest.get("question") or clarification.get("question") or "")
        refined_query = str(manifest.get("refined_query") or question)

        if not question:
            return {"code": 400, "message": "未找到原始研究问题", "data": None}

        research_workflow_service._save_clarification_state(request.session_id, {
            "status": "confirmed",
            "question": question,
            "candidates": [],
            "selected_candidate_id": "",
            "refined_query": refined_query,
            "clarification_summary": str(clarification.get("clarification_summary") or ""),
        })

        logger.info(f"[research {request.session_id}] prepare_rerun: question={question}")
        return {
            "code": 200,
            "message": "success",
            "data": {"question": question, "refined_query": refined_query},
        }
    except Exception as exc:
        logger.error(f"[research {request.session_id}] prepare_rerun failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
