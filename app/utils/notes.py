"""
Notes utility — bridge between the old NoteService API and the new
structured Memory system.

Existing callers (ContextGatherer, Agents) continue to work unchanged.
New code should use app.services.memory directly.
"""

from pathlib import Path
import re
from typing import Any, Iterable

from services.note_service import NoteService
from services.memory import MemoryWriter, MemorySelector, MemoryType


# ---- Old API (kept for backward compat) ----

def get_notes(session_id: str) -> NoteService:
    """Get the legacy NoteService for a session."""
    project_root = Path(__file__).resolve().parents[2]
    notes_dir = project_root / "app" / "data" / "notes"
    return NoteService(session_id, notes_dir)


# ---- New Memory API ----

_memory_writer: MemoryWriter | None = None
_memory_selector: MemorySelector | None = None


def get_memory_writer() -> MemoryWriter:
    """Get the MemoryWriter for the project (cached singleton)."""
    global _memory_writer
    if _memory_writer is None:
        project_root = Path(__file__).resolve().parents[2]
        memory_dir = project_root / "app" / "data" / "memory"
        _memory_writer = MemoryWriter(memory_dir)
    return _memory_writer


def get_memory_selector() -> MemorySelector:
    """Get the MemorySelector for the project (cached singleton)."""
    global _memory_selector
    if _memory_selector is None:
        project_root = Path(__file__).resolve().parents[2]
        memory_dir = project_root / "app" / "data" / "memory"
        _memory_selector = MemorySelector(memory_dir)
    return _memory_selector


async def select_relevant_memories(
    query: str,
    max_results: int = 5,
    llm_call: Any = None,
) -> list[dict[str, Any]]:
    """
    Select relevant memories for a query and return as dicts for context injection.

    Returns list of {title, content, type, importance} dicts compatible
    with the existing ContextGatherer output format.
    """
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
    """
    Evaluate a completed turn and save as memory if warranted.
    Returns the saved entry as a dict, or None.
    """
    writer = get_memory_writer()
    entry = writer.evaluate_and_save(
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


# ---- Filter utilities (unchanged) ----

def _filter_notes(
    notes: Iterable[dict[str, Any]],
    kinds: set[str] | None = None,
    min_importance: float | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Filter and prioritize notes for downstream context building."""
    filtered: list[dict[str, Any]] = []
    for note in notes:
        if not isinstance(note, dict):
            continue

        kind = str(note.get("kind", "")).strip()
        importance = note.get("importance", 0.0)

        if kinds is not None and kind not in kinds:
            continue

        try:
            importance_value = float(importance or 0.0)
        except (TypeError, ValueError):
            importance_value = 0.0

        if min_importance is not None and importance_value < min_importance:
            continue

        filtered.append(note)

    filtered.sort(
        key=lambda item: (
            float(item.get("importance", 0.0) or 0.0),
            str(item.get("updated_at", "")),
        ),
        reverse=True,
    )

    if limit is not None and limit > 0:
        return filtered[:limit]
    return filtered


HIGH_VALUE_NOTE_KINDS = {"decision", "constraint", "summary", "preference", "blocker", "memory"}

LOW_VALUE_NOTE_PATTERNS = (
    "thanks", "thank you", "ok", "okay", "hello", "hi",
    "收到", "谢谢", "好的", "知道了", "明白了", "随便", "无所谓",
)

HIGH_VALUE_NOTE_HINTS = (
    "important", "must", "should", "remember", "constraint",
    "decision", "prefer", "always", "never", "key",
    "important for later",
    "重要", "必须", "约束", "决定", "偏好", "记住", "以后", "不要",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalize_text(text)
    return any(pattern in normalized for pattern in patterns)


def _is_duplicate_note(service: NoteService, title: str, content: str, kind: str) -> bool:
    title_norm = _normalize_text(title)
    content_norm = _normalize_text(content)
    kind_norm = _normalize_text(kind)

    for note in service.list_notes():
        if not isinstance(note, dict):
            continue
        existing = (
            _normalize_text(str(note.get("kind", ""))),
            _normalize_text(str(note.get("title", ""))),
            _normalize_text(str(note.get("content", ""))),
        )
        if existing == (kind_norm, title_norm, content_norm):
            return True
    return False


def should_store_high_value_note(
    title: str,
    content: str,
    kind: str = "note",
    importance: float = 0.5,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    min_importance: float = 0.65,
) -> bool:
    """Decide whether a note is worth persisting."""
    title_text = (title or "").strip()
    content_text = (content or "").strip()
    if not title_text and not content_text:
        return False

    if extra and bool(extra.get("pinned")):
        return True

    combined_text = f"{title_text} {content_text}"
    if _contains_any(combined_text, LOW_VALUE_NOTE_PATTERNS):
        return False

    kind_text = (kind or "note").strip().lower()
    try:
        importance_value = float(importance or 0.0)
    except (TypeError, ValueError):
        importance_value = 0.0

    if kind_text in HIGH_VALUE_NOTE_KINDS:
        return importance_value >= max(0.4, min_importance - 0.1) or len(content_text) >= 24

    if importance_value < min_importance:
        return False

    if _contains_any(combined_text, HIGH_VALUE_NOTE_HINTS):
        return True

    if len(content_text) >= 80 and importance_value >= 0.8:
        return True

    if tags:
        normalized_tags = " ".join(str(tag) for tag in tags)
        if _contains_any(normalized_tags, HIGH_VALUE_NOTE_HINTS):
            return True

    return False


def save_high_value_note(
    session_id: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    kind: str = "note",
    importance: float = 0.5,
    source: str = "manual",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Save a note to both the legacy system and new memory system."""
    # Legacy save
    service = get_notes(session_id)
    if not should_store_high_value_note(
        title=title,
        content=content,
        kind=kind,
        importance=importance,
        tags=tags,
        extra=extra,
    ):
        return None

    if _is_duplicate_note(service, title, content, kind):
        return None

    legacy_result = service.add_note(
        title=title,
        content=content,
        tags=tags,
        kind=kind,
        importance=importance,
        source=source,
        extra=extra,
    )

    # Also save to new memory system
    try:
        writer = get_memory_writer()
        mem_type = _map_kind_to_memory_type(kind)
        writer.save_manual(
            title=title,
            content=content,
            mem_type=mem_type,
            session_id=session_id,
        )
    except Exception:
        pass  # Don't fail if new memory system errors

    return legacy_result


def _map_kind_to_memory_type(kind: str) -> MemoryType:
    """Map old note kind to new MemoryType."""
    mapping = {
        "decision": MemoryType.PROJECT,
        "constraint": MemoryType.FEEDBACK,
        "summary": MemoryType.PROJECT,
        "preference": MemoryType.USER,
        "blocker": MemoryType.PROJECT,
        "memory": MemoryType.REFERENCE,
    }
    return mapping.get(kind, MemoryType.PROJECT)
