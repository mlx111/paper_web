from pathlib import Path
import re
from typing import Any, Iterable

from services.note_service import NoteService


def get_notes(session_id: str) -> NoteService:
    """
    获取当前会话的结构化笔记服务。

    笔记和聊天历史分开保存：
    - chat_history 用来放对话消息
    - notes 用来放长期可复用的结构化记忆
    """
    project_root = Path(__file__).resolve().parents[2]
    notes_dir = project_root / "app" / "data" / "notes"
    return NoteService(session_id, notes_dir)


def _filter_notes(
    notes: Iterable[dict[str, Any]],
    kinds: set[str] | None = None,
    min_importance: float | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Filter and prioritize notes for downstream context building.

    The helper keeps the implementation lightweight:
    - optional kind filtering
    - optional importance threshold
    - stable sorting by importance and recency
    """
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
    "thanks",
    "thank you",
    "ok",
    "okay",
    "hello",
    "hi",
    "收到",
    "谢谢",
    "好的",
    "知道了",
    "明白了",
    "随便",
    "无所谓",
)
HIGH_VALUE_NOTE_HINTS = (
    "important",
    "must",
    "should",
    "remember",
    "constraint",
    "decision",
    "prefer",
    "always",
    "never",
    "key",
    "important for later",
    "重要",
    "必须",
    "约束",
    "决定",
    "偏好",
    "记住",
    "以后",
    "不要",
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
    """
    Decide whether a note is worth persisting.

    The gate is intentionally conservative:
    - empty or boilerplate notes are ignored
    - duplicates are ignored
    - structured high-value kinds are preferred
    - generic notes need stronger signals
    """
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
    """
    Save a note only when it looks high-value enough to keep.

    This is the write-path counterpart to `get_notes`.
    """
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

    return service.add_note(
        title=title,
        content=content,
        tags=tags,
        kind=kind,
        importance=importance,
        source=source,
        extra=extra,
    )
