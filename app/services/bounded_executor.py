"""Run blocking calls without an unbounded executor queue."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock


class WorkerBusy(Exception):
    pass


class BoundedExecutor:
    def __init__(self, max_workers: int):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._slots = BoundedSemaphore(max_workers)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="context")
        self._lock = Lock()
        self.inflight = 0

    async def run(self, function, *args):
        if not self._slots.acquire(blocking=False):
            raise WorkerBusy("Context workers are busy; retry later")
        try:
            future = self._executor.submit(function, *args)
        except BaseException:
            self._slots.release()
            raise
        with self._lock:
            self.inflight += 1

        def release_slot(_):
            with self._lock:
                self.inflight -= 1
            self._slots.release()

        future.add_done_callback(release_slot)
        return await asyncio.wrap_future(future)

    def shutdown(self):
        self._executor.shutdown(wait=True)
