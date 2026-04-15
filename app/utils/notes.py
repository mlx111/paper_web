from pathlib import Path

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
