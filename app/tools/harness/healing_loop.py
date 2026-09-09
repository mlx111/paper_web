"""Healing loop — validate → repair → retry → fallback for tool calls.

The core self-healing mechanism: when a tool call has invalid arguments,
the loop attempts to repair them (first via simple type coercion, then
via LLM repair) and retry. After max_repairs attempts, it falls back to
a degraded result.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from loguru import logger

from ..tool_result import ToolResult
from .schema_validator import ToolSchema, get_schema
from .llm_repair import LLMRepair


class HealingLoop:
    """Self-healing execution loop for tool calls.

    Flow:
        validate(args)
        → if invalid: coerce → LLM repair → retry (max_repairs times)
        → if still invalid: fallback (return error with guidance)
        → if valid: invoke tool → return ToolResult
    """

    def __init__(
        self,
        llm_repair: LLMRepair | None = None,
        max_repairs: int = 2,
    ):
        self.llm_repair = llm_repair
        self.max_repairs = max_repairs

    async def execute_with_healing(
        self,
        tool_name: str,
        args: dict[str, Any],
        raw_invoke_fn: Callable[[dict[str, Any]], Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute *tool_name* with self-healing on argument errors.

        Args:
            tool_name: The tool to execute.
            args: The original arguments (may be invalid).
            raw_invoke_fn: A function that takes args dict and returns raw result.
            context: Optional context dict with 'question' for LLM repair.

        Returns:
            ToolResult with .meta containing healing attempts info.
        """
        schema = get_schema(tool_name)
        question = (context or {}).get("question", "")
        attempts: list[dict[str, Any]] = []
        current_args = dict(args)

        # If no schema defined, skip validation and just invoke
        if schema is None:
            return await self._invoke_raw(tool_name, current_args, raw_invoke_fn, attempts)

        for attempt in range(self.max_repairs + 1):
            # 1. Validate
            vr = schema.validate(current_args)
            attempt_info = {
                "attempt": attempt,
                "args": dict(current_args),
                "validation_ok": vr.ok,
                "errors": [e.message for e in vr.errors] if vr.errors else [],
            }

            if vr.ok:
                # 2. Invoke with validated args
                attempts.append(attempt_info)
                result = await self._invoke_raw(
                    tool_name, vr.coerced_args, raw_invoke_fn, attempts
                )
                # Attach healing metadata
                if len(attempts) > 1 or attempt > 0:
                    result.summary = f"[{tool_name}] healed after {attempt} repair(s) | {result.summary}"
                return result
            else:
                # 3. Try simple coercion first (free, no LLM)
                if attempt == 0 and vr.coerced_args:
                    # Coercion might have partially fixed things
                    coerced_vr = schema.validate(vr.coerced_args)
                    if coerced_vr.ok:
                        attempt_info["coerced_ok"] = True
                        attempts.append(attempt_info)
                        result = await self._invoke_raw(
                            tool_name, coerced_vr.coerced_args, raw_invoke_fn, attempts
                        )
                        result.summary = f"[{tool_name}] healed via type coercion | {result.summary}"
                        return result

                # 4. LLM repair
                if attempt < self.max_repairs and self.llm_repair:
                    logger.info(
                        "HealingLoop: attempting LLM repair for {} (attempt {}/{})",
                        tool_name, attempt + 1, self.max_repairs,
                    )
                    repaired = await self.llm_repair.repair(
                        tool_name, schema, current_args, vr.errors, question
                    )
                    if repaired is not None:
                        attempt_info["repaired"] = True
                        attempts.append(attempt_info)
                        current_args = repaired
                        continue  # retry with repaired args
                    else:
                        attempt_info["repair_failed"] = True
                        attempts.append(attempt_info)
                        continue
                else:
                    attempts.append(attempt_info)
                    # 5. Fallback — return error with guidance
                    return ToolResult.failure(
                        f"Tool '{tool_name}' argument validation failed after "
                        f"{self.max_repairs} repair attempt(s). "
                        f"Errors: {'; '.join(e.message for e in vr.errors)}. "
                        f"Original args: {args}",
                        "REPAIR_FAILED",
                    )

        # Shouldn't reach here, but just in case
        return ToolResult.failure(
            f"HealingLoop exhausted for {tool_name}",
            "HEALING_EXHAUSTED",
        )

    async def _invoke_raw(
        self,
        tool_name: str,
        args: dict[str, Any],
        raw_invoke_fn: Callable,
        attempts: list[dict[str, Any]],
    ) -> ToolResult:
        """Invoke the underlying tool and normalize the result."""
        try:
            raw = raw_invoke_fn(args)
            # Handle async tools
            if asyncio.iscoroutine(raw):
                raw = await raw
        except Exception as exc:
            logger.error("HealingLoop: {} execution failed — {}", tool_name, exc)
            return ToolResult.failure(str(exc), "TOOL_EXECUTION_ERROR")

        result = ToolResult.from_raw(raw, tool_name)
        if not result.summary:
            result.summary = result.to_summary(tool_name)
        return result
