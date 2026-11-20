import asyncio
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.chat_capacity import ChatCapacity, ChatCapacityError


class ChatCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_overload_rejects_immediately_and_recovers_after_release(self):
        capacity = ChatCapacity(max_inflight=1)
        first = await capacity.acquire("session-a", kind="stream")

        with self.assertRaises(ChatCapacityError) as caught:
            await asyncio.wait_for(capacity.acquire("session-b"), timeout=0.2)
        self.assertEqual(caught.exception.status_code, 429)

        await first.release("completed")
        second = await capacity.acquire("session-b")
        await second.release("completed")
        snapshot = await capacity.snapshot()
        self.assertEqual(snapshot["inflight"], 0)
        self.assertEqual(snapshot["rejected_overload"], 1)
        self.assertEqual(snapshot["completed"], 2)

    async def test_same_session_is_rejected_and_release_is_idempotent(self):
        capacity = ChatCapacity(max_inflight=2)
        first = await capacity.acquire("same-session")

        with self.assertRaises(ChatCapacityError) as caught:
            await capacity.acquire("same-session", kind="stream")
        self.assertEqual(caught.exception.status_code, 409)

        await first.release("failed")
        await first.release("failed")
        snapshot = await capacity.snapshot()
        self.assertEqual(snapshot["inflight"], 0)
        self.assertEqual(snapshot["failed"], 1)
        self.assertEqual(snapshot["rejected_session_busy"], 1)

    async def test_stream_slots_are_counted_separately(self):
        capacity = ChatCapacity(max_inflight=2)
        stream = await capacity.acquire("stream", kind="stream")
        ordinary = await capacity.acquire("ordinary", kind="chat")
        self.assertEqual((await capacity.snapshot())["stream_inflight"], 1)

        await stream.release("cancelled")
        await ordinary.release("completed")
        snapshot = await capacity.snapshot()
        self.assertEqual(snapshot["stream_inflight"], 0)
        self.assertEqual(snapshot["cancelled"], 1)
