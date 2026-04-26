"""File module API routes.

This router handles both file uploads and file-based Q&A powered by deep_agent.
"""

import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from agents.file_agent_service import file_agent_service
from models.request import ChatRequest, ClearRequest
from models.response import ApiResponse, SessionInfoResponse
from services.chunk_image_store_service import default_chunk_image_store
from services.vector_index_service import vector_index_service
from utils.rag_utils import rag_utils_service


router = APIRouter(prefix="/file", tags=["文件接口"])

# File upload storage directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = PROJECT_ROOT / "uploads"
ALLOWED_EXTENSIONS = ["txt", "md", "pdf", "doc", "docx", "xls", "xlsx"]
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _format_source_doc(doc) -> dict:
    metadata = getattr(doc, "metadata", {}) or {}
    preview = (getattr(doc, "page_content", "") or "").strip()
    if len(preview) > 240:
        preview = preview[:240].rstrip() + "..."

    score = metadata.get("rerank_score", metadata.get("score"))
    try:
        score = round(float(score), 4) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {
        "filename": metadata.get("filename") or metadata.get("_file_name") or "未知文件",
        "page_number": metadata.get("page_number"),
        "chunk_id": metadata.get("chunk_id") or "",
        "score": score,
        "preview": preview,
    }


def _build_file_sources(question: str, top_k: int = 3) -> list[dict]:
    try:
        retrieved = rag_utils_service.retrieve_documents(question, top_k=top_k)
        docs = retrieved.get("docs", []) if isinstance(retrieved, dict) else []
        sources: list[dict] = []
        seen: set[str] = set()
        for doc in docs:
            source = _format_source_doc(doc)
            key = source.get("chunk_id") or f"{source.get('filename')}:{source.get('page_number')}:{source.get('preview')}"
            if key in seen:
                continue
            seen.add(key)
            sources.append(source)
        return sources
    except Exception as exc:
        logger.warning("文件问答 sources 构建失败: {}", exc)
        return []


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file and index it into the vector store."""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        safe_filename = _sanitize_filename(file.filename)
        file_extension = _get_file_extension(safe_filename)
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式，仅支持: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_path = UPLOAD_DIR / safe_filename
        if file_path.exists():
            logger.info(f"文件已存在，覆盖: {file_path}")
            file_path.unlink()

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE} 字节）",
            )

        file_path.write_bytes(content)
        logger.info(f"文件上传成功: {file_path}")

        try:
            logger.info(f"开始为上传文件创建向量索引: {file_path}")
            vector_index_service.index_single_file(str(file_path))
            logger.info(f"向量索引创建成功: {file_path}")
        except Exception as exc:
            logger.error(f"向量索引创建失败: {file_path}, 错误: {exc}")
            raise HTTPException(status_code=500, detail=f"文件上传成功，但索引创建失败: {exc}")

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success",
                "data": {
                    "filename": safe_filename,
                    "file_path": str(file_path),
                    "size": len(content),
                },
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"文件上传失败: {exc}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {exc}")


@router.post("/index_directory")
async def index_directory(directory_path: str = None):
    """Index all files under a given directory."""
    try:
        logger.info(f"开始索引目录: {directory_path or 'uploads'}")
        result = vector_index_service.index_directory(directory_path)
        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success" if result.success else "partial_success",
                "data": result.to_dict(),
            },
        )
    except Exception as exc:
        logger.error(f"索引目录失败: {exc}")
        raise HTTPException(status_code=500, detail=f"索引目录失败: {exc}")


@router.post("/chat")
async def chat(request: ChatRequest):
    """File module chat entry point powered by deep_agent."""
    try:
        logger.info(f"[file {request.id}] 收到文件问答请求: {request.question}")
        answer = await file_agent_service.query(request.question, session_id=request.id)
        image_map = default_chunk_image_store.resolve_image_map_from_text(answer)
        sources = _build_file_sources(request.question)
        return {
            "code": 200,
            "message": "success",
            "data": {
                "success": True,
                "answer": answer,
                "image_map": image_map,
                "sources": sources,
                "errorMessage": None,
            },
        }
    except Exception as exc:
        logger.error(f"[file {request.id}] 文件问答失败: {exc}")
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
    """Streaming file-module chat entry point."""
    logger.info(f"[file {request.id}] 收到流式文件问答请求: {request.question}")

    async def event_generator():
        answer_parts: list[str] = []
        try:
            async for chunk in file_agent_service.query_stream(request.question, session_id=request.id):
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
                    answer_parts.append(str(chunk_data or ""))
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
                    answer = "".join(answer_parts).strip()
                    image_map = default_chunk_image_store.resolve_image_map_from_text(answer)
                    sources = _build_file_sources(request.question)
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "done",
                                "data": {
                                    "answer": answer,
                                    "image_map": image_map,
                                    "sources": sources,
                                },
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
            logger.error(f"[file {request.id}] 流式文件问答失败: {exc}")
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@router.get("/image/{image_id}")
async def get_chunk_image(image_id: str):
    """Return a locally stored image extracted from an uploaded document."""
    image_path = default_chunk_image_store.get_image_path(image_id)
    if image_path is None:
        raise HTTPException(status_code=404, detail="图片不存在或已过期")
    return FileResponse(image_path)


@router.post("/clear", response_model=ApiResponse)
async def clear_session(request: ClearRequest):
    """Clear file-module session history."""
    try:
        success = file_agent_service.clear_session(request.session_id)
        return ApiResponse(
            status="success" if success else "error",
            message="文件会话已清空" if success else "清空文件会话失败",
            data=None,
        )
    except Exception as exc:
        logger.error(f"[file {request.session_id}] 清空失败: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    """Return the isolated history for a file session."""
    try:
        history = file_agent_service.get_session_history(session_id)
        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(history),
            history=history,
        )
    except Exception as exc:
        logger.error(f"[file {session_id}] 获取会话失败: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


def _get_file_extension(filename: str) -> str:
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        return parts[1].lower()
    return ""


def _sanitize_filename(filename: str) -> str:
    sanitized = filename.replace(" ", "_")
    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
        sanitized = sanitized.replace(char, "_")
    return sanitized
