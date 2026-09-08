"""YAML workflow execution engine — sequential interpreter with tool loop."""

from __future__ import annotations

import asyncio
import ast
import operator
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from loguru import logger

from models.factory import qwen_model
from services.workflow_loader import WorkflowLoader
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

    def add_trace(self, event: str, step: StepDef) -> None:
        trace = self._data.setdefault("_trace", [])
        if isinstance(trace, list):
            trace.append({
                "event": event,
                "step": step.name or step.type,
                "type": step.type,
            })

    def eval_condition(self, expression: str) -> bool:
        """Evaluate simple boolean expressions against context values."""
        expression = self.resolve(expression).strip()
        if not expression:
            return False

        if expression.lower() in ("true", "yes", "1", "ok"):
            return True
        if expression.lower() in ("false", "no", "0", "none"):
            return False

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", expression):
            return self.as_bool(expression)

        try:
            return bool(_SafeConditionEvaluator(self).eval(expression))
        except Exception:
            if expression in self._data:
                return self.as_bool(expression)
            return self.as_bool(expression)


class _SafeConditionEvaluator:
    """Small AST evaluator for workflow conditions."""

    _CMP_OPS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
    }
    _BOOL_OPS = {
        ast.And: all,
        ast.Or: any,
    }

    def __init__(self, ctx: WorkflowContext):
        self.ctx = ctx

    def eval(self, expression: str) -> Any:
        tree = ast.parse(expression, mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.ctx.get(node.id)
        if isinstance(node, ast.Attribute):
            return self.ctx.get(self._attribute_path(node))
        if isinstance(node, ast.BoolOp):
            values = [bool(self._eval_node(v)) for v in node.values]
            op = self._BOOL_OPS[type(node.op)]
            return op(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not bool(self._eval_node(node.operand))
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op_node, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator)
                op = self._CMP_OPS[type(op_node)]
                if not op(left, right):
                    return False
                left = right
            return True
        raise ValueError(f"Unsupported condition node: {type(node).__name__}")

    def _attribute_path(self, node: ast.Attribute) -> str:
        parts = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """Execute a WorkflowDef step by step."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        tool_wrapper: ToolWrapper | None = None,
        workflows: dict[str, WorkflowDef] | None = None,
        workflow_loader: WorkflowLoader | None = None,
    ):
        from tools import tool_registry as default_registry
        self.tool_registry: ToolRegistry = tool_registry or default_registry
        self.tool_wrapper: ToolWrapper = tool_wrapper or ToolWrapper(self.tool_registry)
        self.workflows: dict[str, WorkflowDef] = dict(workflows or {})
        self.workflow_loader = workflow_loader or WorkflowLoader()
        self.trace_service: Any = None
        self.trace_run_id: str = ""

    @staticmethod
    def replay_trace(trace: list[dict[str, Any]] | dict[str, Any]):
        """Yield recorded trace events without re-running workflow side effects."""
        events = trace.get("_trace", []) if isinstance(trace, dict) else trace
        if not isinstance(events, list):
            return
        for idx, event in enumerate(events):
            yield {"type": "replay", "index": idx, "event": event}

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        wf: WorkflowDef,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = WorkflowContext({**wf.parameters, **(params or {})})
        await self._execute_steps(wf.steps, ctx, None, wf.config.max_tool_rounds, wf.config.model_kwargs)
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
                await self._dispatch_step(step, ctx, None, wf.config.max_tool_rounds, wf.config.model_kwargs)
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
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        name_to_index = {
            step.name: idx
            for idx, step in enumerate(steps)
            if step.name
        }
        idx = 0
        jump_count = 0
        max_jumps = max(20, len(steps) * 20)

        while idx < len(steps):
            step = steps[idx]
            ctx.add_trace("step_start", step)
            target = await self._dispatch_step(step, ctx, llm, max_tool_rounds, model_kwargs or {})
            ctx.add_trace("step_end", step)

            if target:
                if target not in name_to_index:
                    raise ValueError(f"goto target not found: {target}")
                idx = name_to_index[target]
                jump_count += 1
                if jump_count > max_jumps:
                    raise RuntimeError("goto jump limit exceeded")
                continue

            idx += 1

    async def _dispatch_step(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
        model_kwargs: dict[str, Any] | None = None,
    ) -> str | None:
        if step.type == "task":
            await self._handle_task(step, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.type == "for_each":
            await self._handle_for_each(step, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.type == "if":
            await self._handle_if(step, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.type == "set_variable":
            self._handle_set_variable(step, ctx)
        elif step.type == "increment":
            self._handle_increment(step, ctx)
        elif step.type == "while":
            await self._handle_while(step, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.type == "parallel":
            await self._handle_parallel(step, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.type in ("call", "submodule"):
            await self._handle_call(step, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.type == "goto":
            return step.target
        else:
            logger.warning("Unknown step type: {}", step.type)
        return None

    # ------------------------------------------------------------------
    # task handler
    # ------------------------------------------------------------------

    async def _handle_task(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        instruction = ctx.resolve(step.instruction)
        tools = self._filter_tools(step.enabled_tools, step.disabled_tools)

        if llm is None:
            init_kwargs = dict(model_kwargs or {})
            init_kwargs.update(step.model_kwargs or {})
            try:
                llm = qwen_model.init_model(steram=False, **init_kwargs)
            except TypeError:
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

        tool_call_payload = {
            "name": name,
            "args": args,
            "id": call_id,
        }
        if self.trace_service is not None and self.trace_run_id:
            result, _ = self.tool_wrapper.execute_tool_message_with_trace(
                tool_call_payload,
                trace_service=self.trace_service,
                run_id=self.trace_run_id,
                node_name="workflow_tool_loop",
            )
        else:
            result, _ = self.tool_wrapper.execute_tool_message(tool_call_payload)

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
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        items = ctx.get(step.in_ref)
        if not isinstance(items, list):
            items = [items] if items else []

        results: list[dict[str, Any]] = []
        for item in items:
            ctx.set(step.item_var, item)
            sub_ctx = WorkflowContext(dict(ctx._data))
            await self._execute_steps(step.steps, sub_ctx, llm, max_tool_rounds, model_kwargs or {})
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
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if ctx.eval_condition(step.condition):
            await self._execute_steps(step.then_steps, ctx, llm, max_tool_rounds, model_kwargs or {})
        elif step.else_steps:
            await self._execute_steps(step.else_steps, ctx, llm, max_tool_rounds, model_kwargs or {})

    # ------------------------------------------------------------------
    # set_variable handler
    # ------------------------------------------------------------------

    def _handle_set_variable(self, step: StepDef, ctx: WorkflowContext) -> None:
        for name, value in step.variables.items():
            resolved = ctx.resolve(value)
            ctx.set(name, resolved)

    def _handle_increment(self, step: StepDef, ctx: WorkflowContext) -> None:
        if not step.target:
            raise ValueError("increment step requires 'var' or 'target'")

        current = ctx.get(step.target, 0)
        try:
            current_number = float(current)
        except (TypeError, ValueError):
            current_number = 0

        amount = float(step.amount)
        new_value = current_number + amount
        if new_value.is_integer():
            ctx.set(step.target, int(new_value))
        else:
            ctx.set(step.target, new_value)

    async def _handle_while(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        for _ in range(step.max_iterations):
            if not ctx.eval_condition(step.condition):
                return
            await self._execute_steps(step.steps, ctx, llm, max_tool_rounds, model_kwargs or {})

        if ctx.eval_condition(step.condition):
            raise RuntimeError(f"while step exceeded max_iterations: {step.name or step.condition}")

    async def _handle_parallel(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        async def _run_branch(branch: StepDef) -> tuple[str, dict[str, Any]]:
            branch_ctx = WorkflowContext(dict(ctx._data))
            await self._execute_steps(branch.steps, branch_ctx, llm, max_tool_rounds, model_kwargs or {})
            return branch.name or f"branch_{id(branch)}", branch_ctx.as_dict()

        pairs = await asyncio.gather(*[_run_branch(branch) for branch in step.branches])
        results = {name: data for name, data in pairs}
        ctx.set(step.save_as or step.name or "parallel", results)

    async def _handle_call(
        self,
        step: StepDef,
        ctx: WorkflowContext,
        llm: Any,
        max_tool_rounds: int,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not step.workflow:
            raise ValueError(f"{step.type} step requires workflow")

        child = self.workflows.get(step.workflow)
        if child is None:
            child = self.workflow_loader.load(step.workflow)
            self.workflows[step.workflow] = child

        resolved_params = {
            str(key): ctx.resolve(str(value)) if isinstance(value, str) else value
            for key, value in step.params.items()
        }
        child_ctx = WorkflowContext({**child.parameters, **resolved_params})
        child_model_kwargs = {**(model_kwargs or {}), **child.config.model_kwargs}
        await self._execute_steps(
            child.steps,
            child_ctx,
            llm,
            child.config.max_tool_rounds or max_tool_rounds,
            child_model_kwargs,
        )

        result = child_ctx.as_dict()
        if step.save_as:
            ctx.set(step.save_as, result)
        else:
            for key, value in result.items():
                ctx.set(key, value)

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
