import concurrent.futures
import sys
import threading
import time
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from utils import memory


def test_simultaneous_memory_writes_are_serialized(monkeypatch):
    active = 0
    observed_max = 0
    state_lock = threading.Lock()

    class Writer:
        def evaluate_and_save(self, *args, **kwargs):
            nonlocal active, observed_max
            with state_lock:
                active += 1
                observed_max = max(observed_max, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return None

    monkeypatch.setattr(memory, "get_memory_writer", lambda: Writer())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda session: memory.save_memory_from_turn("question", "answer", session),
            ("session-a", "session-b"),
        ))
    assert results == [None, None]
    assert observed_max == 1
