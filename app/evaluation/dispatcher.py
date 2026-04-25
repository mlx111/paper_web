from __future__ import annotations

from agents.deep_agent_service import deep_agent_service
from agents.quick_agent_service import quick_agent_service
from agents.router_agent_service import agent_service as router_agent_service


def get_target_agent(mode: str):
    """
    根据 mode 选择被测 agent。

    router:
        走路由器，由它分发到 quick / deep
    quick:
        直接测 quick agent
    deep:
        直接测 deep agent
    """
    mode = (mode or "").strip().lower()

    if mode == "quick":
        return quick_agent_service
    if mode == "deep":
        return deep_agent_service
    return router_agent_service
