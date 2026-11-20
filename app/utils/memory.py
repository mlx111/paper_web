"""Project-scoped structured memory helpers."""

from pathlib import Path
from threading import Lock
from typing import Any

from services.memory import MemorySelector, MemoryWriter


_memory_writer: MemoryWriter | None = None
_memory_selector: MemorySelector | None = None
_memory_write_lock = Lock()


def _memory_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "data" / "memory"


def get_memory_writer() -> MemoryWriter:
    global _memory_writer
    if _memory_writer is None:
        _memory_writer = MemoryWriter(_memory_dir())
    return _memory_writer


def get_memory_selector() -> MemorySelector:
    global _memory_selector
    if _memory_selector is None:
        _memory_selector = MemorySelector(_memory_dir())
    return _memory_selector


async def select_relevant_memories(
    query: str,
    max_results: int = 5,
    llm_call: Any = None,
) -> list[dict[str, Any]]:
    selector = get_memory_selector()
    if llm_call:
        entries = await selector.select(query, max_results=max_results, llm_call=llm_call)
    else:
        entries = selector.select_sync(query, max_results=max_results)

    return [
        {
            "title": entry.name,
            "content": entry.content,
            "kind": entry.type.value,
            "importance": 0.9,
            "tags": ["memory", entry.type.value],
            "metadata": {
                "memory_type": entry.type.value,
                "source_file": entry.name,
                "source_session": entry.source_session_id,
            },
        }
        for entry in entries
    ]


def save_memory_from_turn(
    user_message: str,
    assistant_response: str,
    session_id: str = "",
) -> dict[str, Any] | None:
    with _memory_write_lock:
        entry = get_memory_writer().evaluate_and_save(
            user_message,
            assistant_response,
            session_id=session_id,
        )
    if entry is None:
        return None
    return {
        "title": entry.name,
        "content": entry.content,
        "type": entry.type.value,
        "created_at": entry.created_at,
    }
