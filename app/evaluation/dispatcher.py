from __future__ import annotations

from agents.deep_agent_service import deep_agent_service
from agents.multi_agent_service import multi_agent_service
from agents.quick_agent_service import quick_agent_service


def get_target_agent(mode: str):
    """
    Select the agent under evaluation.

    - quick: 轻量问答 agent（单 agent，少量工具）
    - deep:  深度文件问答 agent（单 agent，全部工具）
    - multi: 多智能体编排（supervisor + searcher/analyzer/citation 子 agent）
    - harness: deep agent + Harness 包装层（guardrail + HITL + healing）
    未知模式回退到 deep 以保持兼容。
    """
    mode = (mode or "").strip().lower()

    if mode == "quick":
        return quick_agent_service
    if mode == "multi":
        return multi_agent_service
    if mode in ("deep", "harness"):
        return deep_agent_service
    return deep_agent_service
