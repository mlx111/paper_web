from pathlib import Path

from services.history_service import HistoryService

def get_history(session_id):
    project_root = Path(__file__).resolve().parents[2]
    return HistoryService(session_id, project_root / "chat_history")
