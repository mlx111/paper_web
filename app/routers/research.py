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


# ============================================================================
# Skill endpoints
# ============================================================================

from services.skill_registry import skill_registry
from pydantic import BaseModel as PydanticBaseModel


class SkillInvokeRequest(PydanticBaseModel):
    variables: dict[str, str] = {}


@router.get("/skills")
async def list_skills():
    """List all available research skills with summaries."""
    try:
        summaries = skill_registry.list_summaries()
        return {
            "code": 200,
            "message": "success",
            "data": {"skills": summaries, "count": len(summaries)},
        }
    except Exception as exc:
        logger.error(f"list_skills failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/skills/search")
async def search_skills(q: str = "", tag: str = ""):
    """Search skills by trigger keyword or tag."""
    try:
        if tag:
            results = skill_registry.find_by_tag(tag)
        elif q:
            results = skill_registry.find_by_trigger(q)
        else:
            results = skill_registry.skills
        return {
            "code": 200,
            "message": "success",
            "data": {
                "skills": [
                    {"name": s.name, "description": s.description, "tags": s.tags}
                    for s in results
                ],
            },
        }
    except Exception as exc:
        logger.error(f"search_skills failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/skills/{name}")
async def get_skill(name: str):
    """Get full skill definition including body template."""
    try:
        skill = skill_registry.get(name)
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
        return {
            "code": 200,
            "message": "success",
            "data": {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "tags": skill.tags,
                "trigger_keywords": skill.trigger_keywords,
                "enabled_tools": skill.enabled_tools,
                "disabled_tools": skill.disabled_tools,
                "body_template": skill.body_template,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"get_skill({name}) failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/skills/{name}/invoke")
async def invoke_skill(name: str, request: SkillInvokeRequest):
    """Resolve a skill's body template with given variables."""
    try:
        body = skill_registry.resolve_body(name, request.variables)
        tools = skill_registry.get_tools(name)
        disabled = skill_registry.get_disabled_tools(name)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "skill_name": name,
                "resolved_body": body,
                "enabled_tools": tools,
                "disabled_tools": disabled,
            },
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    except Exception as exc:
        logger.error(f"invoke_skill({name}) failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/skills/reload")
async def reload_skills():
    """Reload all skills from disk without restarting."""
    try:
        skill_registry.reload()
        return {
            "code": 200,
            "message": f"Skills reloaded: {skill_registry.skill_count} loaded",
            "data": {"count": skill_registry.skill_count},
        }
    except Exception as exc:
        logger.error(f"reload_skills failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Entity graph endpoints
# ============================================================================

from services.entity_extraction_singletons import entity_link_store
from models.entity_link import EntityType


@router.get("/entities/search")
async def search_entities(q: str = "", type: str = ""):
    """Search the entity knowledge graph by name and optional type filter."""
    try:
        entity_type = None
        if type:
            try:
                entity_type = EntityType(type)
            except ValueError:
                pass
        entities = entity_link_store.search_entities(q, entity_type)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "entities": [e.model_dump() for e in entities],
                "count": len(entities),
            },
        }
    except Exception as exc:
        logger.error(f"search_entities failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/entities/stats")
async def entity_stats():
    """Get entity knowledge graph statistics."""
    try:
        return {
            "code": 200,
            "message": "success",
            "data": {
                "entity_count": entity_link_store.entity_count,
                "link_count": entity_link_store.link_count,
            },
        }
    except Exception as exc:
        logger.error(f"entity_stats failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/entities/{slug:path}")
async def get_entity(slug: str):
    """Get entity detail with its outgoing links and backlinks."""
    try:
        entity = entity_link_store.get_entity(slug)
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity not found: {slug}")
        links = entity_link_store.get_links(slug)
        backlinks = entity_link_store.get_backlinks(slug)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "entity": entity.model_dump(),
                "links": [l.model_dump() for l in links],
                "backlinks": [l.model_dump() for l in backlinks],
                "backlink_count": len(backlinks),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"get_entity({slug}) failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
