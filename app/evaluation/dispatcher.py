from __future__ import annotations

from agents.deep_agent_service import deep_agent_service
from agents.quick_agent_service import quick_agent_service


def get_target_agent(mode: str):
    """
    Select the agent under evaluation.

    The UI now routes explicitly by module:
    quick chat uses quick_agent, and file Q&A uses the deep/file chain.
    Unknown evaluation modes fall back to deep for compatibility.
    """
    mode = (mode or "").strip().lower()

    if mode == "quick":
        return quick_agent_service
    if mode == "deep":
        return deep_agent_service
    return deep_agent_service
