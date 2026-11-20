import asyncio
import sys
import threading
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.bounded_executor import BoundedExecutor, WorkerBusy


class BoundedExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_when_worker_busy_and_recovers(self):
        executor = BoundedExecutor(max_workers=1)
        started = threading.Event()
        finish = threading.Event()

        def blocking():
            started.set()
            finish.wait(timeout=1)
            return 7

        first = asyncio.create_task(executor.run(blocking))
        while not started.is_set():
            await asyncio.sleep(0.001)
        with self.assertRaises(WorkerBusy):
            await executor.run(lambda: 8)
        finish.set()
        self.assertEqual(await first, 7)
        self.assertEqual(await executor.run(lambda: 9), 9)
        executor.shutdown()

    async def test_cancel_does_not_release_slot_before_thread_finishes(self):
        executor = BoundedExecutor(max_workers=1)
        started = threading.Event()
        finish = threading.Event()

        def blocking():
            started.set()
            finish.wait(timeout=1)

        task = asyncio.create_task(executor.run(blocking))
        while not started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(WorkerBusy):
            await executor.run(lambda: None)
        finish.set()
        await asyncio.wait_for(_wait_for_idle(executor), timeout=1)
        self.assertIsNone(await executor.run(lambda: None))
        executor.shutdown()


async def _wait_for_idle(executor):
    while executor.inflight:
        await asyncio.sleep(0.001)
