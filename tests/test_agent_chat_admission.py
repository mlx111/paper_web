import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from models.request import ChatRequest
from routers import agent as agent_router
from services.chat_capacity import ChatCapacity


class _SlowAgent:
    def __init__(self):
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def query(self, question, session_id):
        self.started.set()
        await self.finish.wait()
        return "ready"

    async def query_stream(self, question, session_id):
        self.started.set()
        await self.finish.wait()
        yield {"type": "complete", "data": {"answer": "ready"}}


class AgentChatAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_overload_uses_http_429_and_releases_slot(self):
        slow = _SlowAgent()
        capacity = ChatCapacity(1)
        with patch.object(agent_router, "agent_service", slow), patch.object(
            agent_router, "chat_capacity", capacity, create=True
        ):
            first = asyncio.create_task(agent_router.chat(ChatRequest(Id="one", Question="first")))
            await asyncio.wait_for(slow.started.wait(), timeout=1)
            with self.assertRaises(HTTPException) as caught:
                await asyncio.wait_for(
                    agent_router.chat(ChatRequest(Id="two", Question="second")), timeout=0.2
                )
            self.assertEqual(caught.exception.status_code, 429)
            slow.finish.set()
            self.assertEqual((await first)["data"]["answer"], "ready")
            self.assertEqual((await capacity.snapshot())["inflight"], 0)

    async def test_stream_cancellation_releases_slot(self):
        slow = _SlowAgent()
        capacity = ChatCapacity(1)
        with patch.object(agent_router, "agent_service", slow), patch.object(
            agent_router, "chat_capacity", capacity, create=True
        ):
            response = await agent_router.chat_stream(ChatRequest(Id="one", Question="stream"))
            self.assertEqual((await capacity.snapshot())["stream_inflight"], 1)
            iteration = asyncio.create_task(response.body_iterator.__anext__())
            await asyncio.wait_for(slow.started.wait(), timeout=1)
            iteration.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await iteration
            self.assertEqual((await capacity.snapshot())["stream_inflight"], 0)

    async def test_stream_disconnect_before_first_event_releases_slot(self):
        capacity = ChatCapacity(1)
        with patch.object(agent_router, "chat_capacity", capacity, create=True):
            response = await agent_router.chat_stream(ChatRequest(Id="one", Question="stream"))
            sent = []

            async def send(message):
                sent.append(message)

            async def receive():
                return {"type": "http.disconnect"}

            await asyncio.wait_for(
                response({"type": "http", "method": "POST", "path": "/agent/chat_stream"}, receive, send),
                timeout=1,
            )
            self.assertEqual((await capacity.snapshot())["inflight"], 0)

    async def test_chat_timeout_releases_slot(self):
        slow = _SlowAgent()
        capacity = ChatCapacity(1)
        with patch.object(agent_router, "agent_service", slow), patch.object(
            agent_router, "chat_capacity", capacity, create=True
        ), patch.object(agent_router.config, "chat_timeout_seconds", 0.01, create=True):
            with self.assertRaises(HTTPException) as caught:
                await asyncio.wait_for(
                    agent_router.chat(ChatRequest(Id="one", Question="slow")), timeout=1
                )
            self.assertEqual(caught.exception.status_code, 504)
            self.assertEqual((await capacity.snapshot())["inflight"], 0)

    async def test_stream_timeout_emits_error_and_releases_slot(self):
        slow = _SlowAgent()
        capacity = ChatCapacity(1)
        with patch.object(agent_router, "agent_service", slow), patch.object(
            agent_router, "chat_capacity", capacity, create=True
        ), patch.object(agent_router.config, "chat_timeout_seconds", 0.01, create=True):
            response = await agent_router.chat_stream(ChatRequest(Id="one", Question="slow"))
            event = await asyncio.wait_for(response.body_iterator.__anext__(), timeout=1)
            self.assertIn('"type": "error"', event["data"])
            with self.assertRaises(StopAsyncIteration):
                await response.body_iterator.__anext__()
            self.assertEqual((await capacity.snapshot())["inflight"], 0)

    async def test_stream_error_event_counts_as_failure(self):
        class ErrorAgent:
            async def query_stream(self, question, session_id):
                yield {"type": "error", "data": "upstream failed"}

        capacity = ChatCapacity(1)
        with patch.object(agent_router, "agent_service", ErrorAgent()), patch.object(
            agent_router, "chat_capacity", capacity, create=True
        ):
            response = await agent_router.chat_stream(ChatRequest(Id="one", Question="error"))
            events = [event async for event in response.body_iterator]
            self.assertEqual(len(events), 1)
            self.assertEqual((await capacity.snapshot())["failed"], 1)
