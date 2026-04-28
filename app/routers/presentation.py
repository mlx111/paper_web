import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from agents.presentation_workflow_service import presentation_workflow_service
from models.request import ClearRequest, PresentationMaterialsRequest, PresentationRequest
from models.response import ApiResponse, SessionInfoResponse


router = APIRouter(prefix="/presentation", tags=["presentation"])


def _artifact_filename(artifact_name: str) -> str:
    return {
        "outline": "outline.json",
        "layout": "layout.json",
        "schema": "schema.json",
        "design": "design.json",
        "manifest": "artifact_manifest.json",
        "quality": "quality_report.json",
        "pptx": "output.pptx",
        "plan": "plan.json",
        "manuscript": "manuscript.md",
    }.get(artifact_name, artifact_name)


@router.get("/materials/{session_id}")
async def list_materials(session_id: str):
    try:
        return {"code": 200, "message": "success", "data": presentation_workflow_service.material_service.load_materials(session_id)}
    except Exception as exc:
        logger.error("[presentation {}] load materials failed: {}", session_id, exc)
        return {"code": 500, "message": "error", "data": {"materials": [], "errorMessage": str(exc)}}


@router.post("/materials")
async def save_materials(request: PresentationMaterialsRequest):
    try:
        result = presentation_workflow_service.material_service.save_material_entries(
            request.session_id,
            [item.model_dump(by_alias=False) for item in request.materials],
        )
        return {"code": 200, "message": "success", "data": result}
    except Exception as exc:
        logger.error("[presentation {}] save materials failed: {}", request.session_id, exc)
        return {"code": 500, "message": "error", "data": {"errorMessage": str(exc)}}


@router.post("/materials/upload")
async def upload_material(session_id: str = Form(...), file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = presentation_workflow_service.material_service.save_uploaded_material(
            session_id,
            file.filename or "upload.bin",
            content,
            mime_type=file.content_type,
        )
        return {"code": 200, "message": "success", "data": result}
    except Exception as exc:
        logger.error("[presentation {}] upload material failed: {}", session_id, exc)
        return {"code": 500, "message": "error", "data": {"errorMessage": str(exc)}}


@router.get("/download/{session_id}/{artifact_name}")
async def download_artifact(session_id: str, artifact_name: str):
    paths = presentation_workflow_service._build_artifact_paths(session_id)
    path_map = {
        "outline": paths["outline_path"],
        "layout": paths["layout_path"],
        "schema": paths["schema_path"],
        "design": paths["design_path"],
        "manifest": paths["artifact_manifest_path"],
        "quality": paths["quality_report_path"],
        "pptx": paths["pptx_path"],
        "plan": paths["plan_path"],
        "manuscript": paths["manuscript_path"],
    }
    file_path = path_map.get(artifact_name)
    if file_path is None or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    media_type = {
        "outline": "application/json",
        "layout": "application/json",
        "schema": "application/json",
        "design": "application/json",
        "manifest": "application/json",
        "quality": "application/json",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "plan": "application/json",
        "manuscript": "text/markdown; charset=utf-8",
    }.get(artifact_name)
    return FileResponse(file_path, filename=_artifact_filename(artifact_name), media_type=media_type)


@router.post("/chat")
async def chat(request: PresentationRequest):
    try:
        result = presentation_workflow_service.run_topic(
            request.session_id,
            request.topic,
            request.target_pages,
            research_session_id=request.research_session_id,
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


@router.post("/quality", response_model=ApiResponse)
async def quality_check(request: ClearRequest):
    try:
        report = presentation_workflow_service.check_quality(request.session_id)
        return ApiResponse(status="success", message="演示质量检查完成", data=report)
    except Exception as exc:
        logger.error("[presentation {}] quality check failed: {}", request.session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/regenerate", response_model=ApiResponse)
async def regenerate_presentation(request: ClearRequest):
    try:
        result = presentation_workflow_service.regenerate_from_artifacts(request.session_id)
        return ApiResponse(status="success", message="演示已基于保存工件重新生成", data=result)
    except Exception as exc:
        logger.error("[presentation {}] regenerate failed: {}", request.session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


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
        artifacts = history[-1].get("artifacts") if history else None
        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(history),
            history=history,
            artifacts=artifacts,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
