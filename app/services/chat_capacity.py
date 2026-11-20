"""Per-process admission control for interactive agent requests."""

from collections import deque
from threading import Lock
from time import perf_counter


class ChatCapacityError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ChatLease:
    def __init__(self, capacity: "ChatCapacity", session_id: str, kind: str):
        self._capacity = capacity
        self.session_id = session_id
        self.kind = kind
        self._started = perf_counter()
        self._released = False

    async def release(self, outcome: str = "completed") -> None:
        self._capacity._release(self, outcome)


class ChatCapacity:
    def __init__(self, max_inflight: int):
        if max_inflight < 1:
            raise ValueError("max_inflight must be positive")
        self.max_inflight = max_inflight
        self._lock = Lock()
        self._sessions: set[str] = set()
        self._inflight = 0
        self._stream_inflight = 0
        self._observed_max = 0
        self._accepted = 0
        self._rejected_overload = 0
        self._rejected_session_busy = 0
        self._outcomes = {"completed": 0, "failed": 0, "cancelled": 0}
        self._duration_ms: deque[int] = deque(maxlen=512)

    async def acquire(self, session_id: str, kind: str = "chat") -> ChatLease:
        with self._lock:
            if session_id in self._sessions:
                self._rejected_session_busy += 1
                raise ChatCapacityError(409, "This session already has an active chat request")
            if self._inflight >= self.max_inflight:
                self._rejected_overload += 1
                raise ChatCapacityError(429, "Chat capacity is full; retry later")
            self._sessions.add(session_id)
            self._inflight += 1
            self._stream_inflight += int(kind == "stream")
            self._accepted += 1
            self._observed_max = max(self._observed_max, self._inflight)
        return ChatLease(self, session_id, kind)

    def _release(self, lease: ChatLease, outcome: str) -> None:
        with self._lock:
            if lease._released:
                return
            lease._released = True
            self._sessions.remove(lease.session_id)
            self._inflight -= 1
            self._stream_inflight -= int(lease.kind == "stream")
            self._outcomes[outcome if outcome in self._outcomes else "failed"] += 1
            self._duration_ms.append(int((perf_counter() - lease._started) * 1000))

    async def snapshot(self) -> dict:
        with self._lock:
            durations = sorted(self._duration_ms)
            p95 = durations[max(0, (95 * len(durations) + 99) // 100 - 1)] if durations else 0
            return {
                "scope": "process",
                "max_inflight": self.max_inflight,
                "inflight": self._inflight,
                "stream_inflight": self._stream_inflight,
                "observed_max": self._observed_max,
                "accepted": self._accepted,
                "rejected_overload": self._rejected_overload,
                "rejected_session_busy": self._rejected_session_busy,
                **self._outcomes,
                "recent_duration_p95_ms": p95,
            }
