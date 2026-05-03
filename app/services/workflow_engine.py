"""YAML workflow execution engine — sequential interpreter with tool loop."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from loguru import logger

from models.factory import qwen_model
from services.workflow_loader import StepDef, WorkflowDef, extract_template_vars
from tools.tool_registry import ToolRegistry
from tools.tool_wrapper import ToolWrapper


# ---------------------------------------------------------------------------
# WorkflowContext
# ---------------------------------------------------------------------------

class WorkflowContext:
    """Mutable variable store with dot-path traversal and template resolution."""

    def __init__(self, initial: dict[str, Any] | None = None):
        self._data: dict[str, Any] = dict(initial or {})

    def get(self, path: str, default: Any = "") -> Any:
        """Traverse dot-separated path. Returns default if any key is missing."""
        keys = path.split(".")
        current: Any = self._data
        for key in keys:
            if isinstance(current, dict):
                if key not in current:
                    return default
                current = current[key]
            elif isinstance(current, list):
                try:
                    current = current[int(key)]
                except (IndexError, ValueError):
                    return default
            else:
                return default
        return current if current is not None else default

    def set(self, path: str, value: Any) -> None:
        """Set value at dot-separated path, creating intermediate dicts as needed."""
        keys = path.split(".")
        current = self._data
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    def resolve(self, template: str) -> str:
        """Replace all {{variable}} placeholders with context values."""
        def _replace(match: re.Match) -> str:
            var_path = match.group(1).strip()
            value = self.get(var_path)
            if isinstance(value, dict):
                import json
                return json.dumps(value, ensure_ascii=False)
            if isinstance(value, list):
                import json
                return json.dumps(value, ensure_ascii=False)
            return str(value)
        return re.sub(r"\{\{(.+?)\}\}", _replace, template)

    def as_bool(self, path: str) -> bool:
        """Evaluate a context path as boolean."""
        value = self.get(path)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1", "ok")
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, (list, dict)):
            return len(value) > 0
        return False

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """Execute a WorkflowDef step by step."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        tool_wrapper: ToolWrapper | None = None,
    ):
        from tools import tool_registry as default_registry
        self.tool_registry: ToolRegistry = tool_registry or default_registry
        self.tool_wrapper: ToolWrapper = tool_wrapper or ToolWrapper(self.tool_registry)

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        wf: WorkflowDef,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = WorkflowContext({**wf.parameters, **(params or {})})
        await self._execute_steps(wf.steps, ctx, None, wf.config.max_tool_rounds)
        return ctx.as_dict()

    async def run_stream(
        self,
        wf: WorkflowDef,
        params: dict[str, Any] | None = None,
    ):
        """Async generator yielding typed events during execution."""
        ctx = WorkflowContext({**wf.parameters, **(params or {})})

        yield {"type": "start", "workflow": wf.name}

        for step in wf.steps:
            yield {"type": "step_start", "step": step.name or step.type}
            try:
                await self._dispatch_step(step, ctx, None, wf.config.max_tool_rounds)
            except Exception as exc:
                yield {"type": "step_error", "step": step.name or step.type, "error": str(exc)}
                logger.error("Step {} failed: {}", step.name, exc)
                break
            yield {"type": "step_end", "step": step.name or step.type}

        yield {"type": "done", "output": ctx.as_dict()}

    # ------------------------------------------------------------------
    # step dispatcher
    # ------------------------------------------------------------------

    async def _execute_steps(
        self,
        steps: list[StepDef],
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
    ) -> None:
        for step in steps:
            await self._dispatch_step(step, ctx, llm, max_tool_rounds)

    async def _dispatch_step(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
    ) -> None:
        if step.type == "task":
            await self._handle_task(step, ctx, llm, max_tool_rounds)
        elif step.type == "for_each":
            await self._handle_for_each(step, ctx, llm, max_tool_rounds)
        elif step.type == "if":
            await self._handle_if(step, ctx, llm, max_tool_rounds)
        elif step.type == "set_variable":
            self._handle_set_variable(step, ctx)
        else:
            logger.warning("Unknown step type: {}", step.type)

    # ------------------------------------------------------------------
    # task handler
    # ------------------------------------------------------------------

    async def _handle_task(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
    ) -> None:
        instruction = ctx.resolve(step.instruction)
        tools = self._filter_tools(step.enabled_tools, step.disabled_tools)

        if llm is None:
            llm = qwen_model.init_model(steram=False)
        bound_llm = llm.bind_tools(tools) if tools else llm

        messages: list = [SystemMessage(content=instruction)]
        response = await bound_llm.ainvoke(messages)
        messages.append(response)

        # tool-call loop
        for _ in range(max_tool_rounds):
            if not getattr(response, "tool_calls", None):
                break

            tool_results: list = []
            for tc in response.tool_calls:
                result_msg = self._execute_single_tool(tc)
                tool_results.append(result_msg)

            messages.extend(tool_results)
            response = await bound_llm.ainvoke(messages)
            messages.append(response)

        # save output
        content = getattr(response, "content", "") or ""
        if step.save_as:
            ctx.set(step.save_as, content.strip())

    def _execute_single_tool(self, tool_call: Any) -> ToolMessage:
        name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")
        args = tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {})
        call_id = tool_call.get("id", "") if isinstance(tool_call, dict) else getattr(tool_call, "id", "")

        result, _ = self.tool_wrapper.execute_tool_message({
            "name": name,
            "args": args,
            "id": call_id,
        })

        return ToolMessage(
            content=result.to_message_content(),
            name=name,
            tool_call_id=call_id,
        )

    # ------------------------------------------------------------------
    # for_each handler
    # ------------------------------------------------------------------

    async def _handle_for_each(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
    ) -> None:
        items = ctx.get(step.in_ref)
        if not isinstance(items, list):
            items = [items] if items else []

        results: list[dict[str, Any]] = []
        for item in items:
            ctx.set(step.item_var, item)
            sub_ctx = WorkflowContext(dict(ctx._data))
            await self._execute_steps(step.steps, sub_ctx, llm, max_tool_rounds)
            results.append(sub_ctx.as_dict())

        # merge results back
        if step.name:
            ctx.set(step.name, results)

    # ------------------------------------------------------------------
    # if handler
    # ------------------------------------------------------------------

    async def _handle_if(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
    ) -> None:
        condition = ctx.resolve(step.condition)
        # If resolve didn't change the string, treat it as a context path
        if condition == step.condition and step.condition:
            condition = str(ctx.get(step.condition))
        if condition.lower() in ("true", "yes", "1", "ok"):
            await self._execute_steps(step.then_steps, ctx, llm, max_tool_rounds)
        elif step.else_steps:
            await self._execute_steps(step.else_steps, ctx, llm, max_tool_rounds)

    # ------------------------------------------------------------------
    # set_variable handler
    # ------------------------------------------------------------------

    def _handle_set_variable(self, step: StepDef, ctx: WorkflowContext) -> None:
        for name, value in step.variables.items():
            resolved = ctx.resolve(value)
            ctx.set(name, resolved)

    # ------------------------------------------------------------------
    # tool filtering
    # ------------------------------------------------------------------

    def _filter_tools(self, enabled: list[str], disabled: list[str]) -> list:
        """Filter the global tool_registry by enabled/disabled lists."""
        all_tools = self.tool_registry.get_tools_list()

        # "*" in disabled means disable all
        if disabled and disabled[0] == "*":
            return []

        if not enabled and not disabled:
            return all_tools

        filtered: list = []
        for tool in all_tools:
            if disabled and tool.name in disabled:
                continue
            if enabled and tool.name not in enabled:
                continue
            filtered.append(tool)

        return filtered
