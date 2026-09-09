from __future__ import annotations

from settings.config import config

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


_simple_quick_agent = None


def _get_simple_quick_agent():
    """懒加载「简单问题专用」quick agent（廉价模型档）。"""
    global _simple_quick_agent
    if _simple_quick_agent is None:
        from agents.quick_agent_service import QuickAgentService

        _simple_quick_agent = QuickAgentService(
            streaming=True,
            model_name=config.routing_simple_model,
        )
    return _simple_quick_agent


def resolve_target_agent(mode: str, query: str = ""):
    """返回 (agent, routing_info)。

    仅 quick 模式启用意图感知模型路由（MODEL_ROUTING_ENABLED 开关）：
    简单问题（实体问答/短寒暄）→ 廉价模型，其余 → 默认模型。
    """
    mode = (mode or "").strip().lower()
    if mode != "quick" or not config.model_routing_enabled:
        return get_target_agent(mode), {}

    from services.model_routing_service import model_routing_service

    is_simple, reason = model_routing_service.is_simple_query(query)
    if is_simple:
        agent = _get_simple_quick_agent()
        return agent, {
            "routed": True,
            "route_tier": "simple",
            "route_reason": reason,
        }
    agent = get_target_agent(mode)
    return agent, {
        "routed": True,
        "route_tier": "complex",
        "route_reason": reason,
    }
