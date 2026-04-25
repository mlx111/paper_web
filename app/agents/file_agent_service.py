from __future__ import annotations

from agents.deep_agent_service import DeepAgentService
from utils.history import get_file_history


file_agent_service = DeepAgentService(streaming=True, history_loader=get_file_history)
