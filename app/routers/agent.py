"""对话接口

提供基于 RAG Agent 的普通对话和流式对话接口
"""

import asyncio
import json
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from models.request import ChatRequest, ClearRequest
from models.response import SessionInfoResponse, ApiResponse
from agents.quick_agent_service import quick_agent_service as agent_service
from services.bounded_executor import WorkerBusy
from services.chat_capacity import ChatCapacity, ChatCapacityError
from settings.config import config
from loguru import logger

router = APIRouter(prefix="/agent", tags=["对话接口"])
chat_capacity = ChatCapacity(max(1, config.chat_max_inflight))


def _capacity_http_error(exc: ChatCapacityError) -> HTTPException:
    headers = {"Retry-After": "1"} if exc.status_code == 429 else None
    return HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers)


@router.get("/capacity")
async def capacity_snapshot():
    """Expose local admission counters for load tests and operations."""
    return await chat_capacity.snapshot()



@router.post("/chat")
async def chat(request: ChatRequest):
    """快速对话接口
    {
        "code": 200,
        "message": "success",
        "data": {
            "success": true,
            "answer": "回答内容",
            "errorMessage": null
        }
    }

    Args:
        request: 对话请求

    Returns:
        统一格式的对话响应
    """
    try:
        lease = await chat_capacity.acquire(request.id)
    except ChatCapacityError as exc:
        raise _capacity_http_error(exc) from exc

    outcome = "failed"
    try:
        logger.info(f"[会话 {request.id}] 收到快速对话请求: {request.question}")
        async with asyncio.timeout(max(0.001, config.chat_timeout_seconds)):
            answer = await agent_service.query(
                request.question,
                session_id=request.id
            )

        logger.info(f"[会话 {request.id}] 快速对话完成")
        outcome = "completed"

        return {
            "code": 200,
            "message": "success",
            "data": {
                "success": True,
                "answer": answer,
                "errorMessage": None
            }
        }

    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except TimeoutError as exc:
        logger.warning("快速对话超时，会话: {}", request.id)
        raise HTTPException(status_code=504, detail="Chat request timed out") from exc
    except WorkerBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "1"}) from exc
    except Exception as e:
        logger.error(f"对话接口错误: {e}")
        return {
            "code": 500,
            "message": "error",
            "data": {
                "success": False,
                "answer": None,
                "errorMessage": str(e)
            }
        }
    finally:
        await lease.release(outcome)

@router.post("/chat_stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口（基于 RAG Agent，SSE）

    返回 SSE 格式，data 字段为 JSON：

    工具调用事件:
    event: message
    data: {"type":"tool_call","data":{"tool":"工具名","status":"start|end","input":{...}}}

    内容流式事件:
    event: message
    data: {"type":"content","data":"内容块"}

    完成事件:
    event: message
    data: {"type":"done","data":{"answer":"完整答案","tool_calls":[...]}}

    Args:
        request: 对话请求

    Returns:
        SSE 事件流
    """
    try:
        lease = await chat_capacity.acquire(request.id, kind="stream")
    except ChatCapacityError as exc:
        raise _capacity_http_error(exc) from exc

    logger.info(f"[会话 {request.id}] 收到流式对话请求: {request.question}")

    async def event_generator():
        outcome = "failed"
        saw_error = False
        try:
            async for chunk in _timed_stream(request):
                chunk_type = chunk.get("type", "unknown")
                chunk_data = chunk.get("data", None)

                if chunk_type == "context":
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "context",
                            "data": chunk_data
                        }, ensure_ascii=False)
                    }
                # 处理调试类型消息（新增）
                elif chunk_type == "debug":
                    # 调试信息，可以选择发送或忽略
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "debug",
                            "node": chunk.get("node", "unknown"),
                            "message_type": chunk.get("message_type", "unknown")
                        }, ensure_ascii=False)
                    }
                elif chunk_type == "tool_call":
                    # 发送工具调用事件（可选，前端可以显示工具调用状态）
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "tool_call",
                            "data": chunk_data
                        }, ensure_ascii=False)
                    }
                elif chunk_type == "search_results":
                    # 发送检索结果（可选，前端可以忽略）
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "search_results",
                            "data": chunk_data
                        }, ensure_ascii=False)
                    }
                elif chunk_type == "content":
                    # 发送内容块 - 关键：data 必须是 JSON 字符串
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "content",
                            "data": chunk_data
                        }, ensure_ascii=False)
                    }
                elif chunk_type == "complete":
                    # 发送完成信号
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "done",
                            "data": chunk_data
                        }, ensure_ascii=False)
                    }
                elif chunk_type == "error":
                    saw_error = True
                    # 发送错误信息
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "error",
                            "data": str(chunk_data)
                        }, ensure_ascii=False)
                    }

            logger.info(f"[会话 {request.id}] 流式对话完成")
            outcome = "failed" if saw_error else "completed"

        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as e:
            logger.error(f"流式对话接口错误: {e}")
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "error",
                    "data": str(e)
                }, ensure_ascii=False)
            }
        finally:
            await lease.release(outcome)

    try:
        return EventSourceResponse(event_generator())
    except BaseException:
        await lease.release("failed")
        raise


async def _timed_stream(request: ChatRequest):
    async with asyncio.timeout(max(0.001, config.chat_timeout_seconds)):
        async for chunk in agent_service.query_stream(request.question, session_id=request.id):
            yield chunk


@router.post("/chat/clear", response_model=ApiResponse)
async def clear_session(request: ClearRequest):
    """清空会话历史

    Args:
        request: 清空请求

    Returns:
        操作结果
    """
    try:
        success = agent_service.clear_session(request.session_id)
        logger.info(f"清空会话: {request.session_id}, 结果: {success}")

        return ApiResponse(
            status="success" if success else "error",
            message="会话已清空" if success else "清空会话失败",
            data=None
        )

    except Exception as e:
        logger.error(f"清空会话错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    """查询会话历史

    Args:
        session_id: 会话 ID

    Returns:
        会话信息
    """
    try:
        history = agent_service.get_session_history(session_id)

        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(history),
            history=history
        )

    except Exception as e:
        logger.error(f"获取会话信息错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))
