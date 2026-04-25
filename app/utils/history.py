from __future__ import annotations

from pathlib import Path

from services.history_service import HistoryService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_chat_history(session_id: str):
    return HistoryService(session_id, PROJECT_ROOT / "chat_history")


def get_file_history(session_id: str):
    return HistoryService(session_id, PROJECT_ROOT / "file_history")


def get_history(session_id: str):
    """
    Backward-compatible alias for the default chat history.
    """
    return get_chat_history(session_id)
