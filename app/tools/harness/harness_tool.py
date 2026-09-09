"""Harness tool wrapper — chains guardrails, HITL, and healing.

Instead of subclassing BaseTool (which has pydantic inheritance complexities),
we use a factory function that creates StructuredTool instances with a
coroutine that runs the full harness chain:

    1. Guardrail pre-check (injection detection + authorization)
    2. HITL check (if permission="ask_user", return pending)
    3. Self-healing loop (validate → repair → invoke → fallback)
    4. Guardrail post-check (output injection filtering)
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from loguru import logger

from ..tool_result import ToolResult
from .guardrails import GuardrailChain
from .healing_loop import HealingLoop
from .llm_repair import LLMRepair
from .hitl_manager import hitl_manager

# Shared harness instances (lazy-init)
_guardrail: GuardrailChain | None = None
_healing_loop: HealingLoop | None = None


def _get_guardrail() -> GuardrailChain:
    global _guardrail
    if _guardrail is None:
        _guardrail = GuardrailChain()
    return _guardrail


def _get_healing_loop() -> HealingLoop:
    global _healing_loop
    if _healing_loop is None:
        _healing_loop = HealingLoop(llm_repair=None, max_repairs=2)
    return _healing_loop


def set_healing_model(model: Any) -> None:
    """Set the LLM model for healing repair. Call during agent init."""
    global _healing_loop
    _healing_loop = HealingLoop(llm_repair=LLMRepair(model=model), max_repairs=2)


async def _harness_coroutine(
    tool_name: str,
    underlying: BaseTool,
    permission: str,
    **kwargs: Any,
) -> str:
    """The coroutine that runs the full harness chain for a tool call."""
    args = dict(kwargs)
    guardrail = _get_guardrail()

    # 1. Guardrail pre-check
    pre = guardrail.pre_check(tool_name, args, "")
    if pre is not None:
        logger.info("Harness: {} blocked by guardrail: {}",
                    tool_name, pre.error_code)
        return pre.to_message_content()

    # 2. HITL check
    if permission == "ask_user":
        result = hitl_manager.request_approval(tool_name, args, "", "")
        return result.to_message_content()

    # 3. Self-healing loop
    healing = _get_healing_loop()
    result = await healing.execute_with_healing(
        tool_name,
        args,
        raw_invoke_fn=lambda a: underlying.invoke(a),
        context={"question": ""},
    )

    # 4. Guardrail post-check
    result = guardrail.post_check(tool_name, result)

    return result.to_message_content()


def wrap_with_harness(
    tool: BaseTool,
    permission: str = "allow",
) -> BaseTool:
    """Wrap a BaseTool with the harness chain (guardrails + HITL + healing).

    Returns a new StructuredTool that intercepts all calls to the original.
    """
    # Extract the args schema from the original tool
    args_schema = getattr(tool, "args_schema", None)

    # If no args_schema, create a minimal one from the tool's input schema
    if args_schema is None:
        from pydantic import create_model
        # Try to get input schema from the tool
        schema_dict = getattr(tool, "args_schema_model", None)
        if schema_dict:
            args_schema = create_model(
                f"{tool.name}_args",
                **{k: (v.get("type", str), ...) for k, v in schema_dict.items()}
            )

    async def _coro(**kwargs: Any) -> str:
        return await _harness_coroutine(tool.name, tool, permission, **kwargs)

    def _sync(**kwargs: Any) -> str:
        # Sync wrapper: run the async coroutine in an event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in an async context — use a thread pool
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _coro(**kwargs))
                    return future.result(timeout=120)
            else:
                return asyncio.run(_coro(**kwargs))
        except RuntimeError:
            return asyncio.run(_coro(**kwargs))

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=args_schema,
        func=_sync,
        coroutine=_coro,
    )


def wrap_tools_with_harness(
    tools: list[BaseTool],
    permissions: dict[str, str] | None = None,
) -> list[BaseTool]:
    """Wrap a list of tools with the harness chain.

    Args:
        tools: List of BaseTool instances to wrap.
        permissions: Optional dict mapping tool name → permission ("allow"/"ask_user").
                     Tools not in the dict default to "allow".

    Returns:
        List of wrapped StructuredTool instances.
    """
    permissions = permissions or {}
    return [
        wrap_with_harness(t, permission=permissions.get(t.name, "allow"))
        for t in tools
    ]
