"""Tests for YAML workflow loader, context, engine, and step handlers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow_loader import (
    StepDef,
    WorkflowConfig,
    WorkflowDef,
    WorkflowLoader,
    extract_template_vars,
)
from app.services.workflow_engine import WorkflowContext, WorkflowEngine


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sample_def(steps: list[StepDef]) -> WorkflowDef:
    return WorkflowDef(name="test", steps=steps)


def _task_step(name: str = "t1", instruction: str = "do {{x}}", save_as: str = "out") -> StepDef:
    return StepDef(type="task", name=name, instruction=instruction, save_as=save_as)


# ---------------------------------------------------------------------------
# TestWorkflowLoader
# ---------------------------------------------------------------------------

class TestWorkflowLoader:
    def test_parse_valid_yaml(self, tmp_path):
        yaml_content = """
name: my_workflow
description: A test workflow
config:
  model: qwen-test
  max_tool_rounds: 2
parameters:
  topic: AI
workflow:
  - task:
      name: step1
      instruction: "Search: {{topic}}"
      enabled_tools:
        - tool_a
      save_as: result
"""
        path = tmp_path / "my_workflow.yaml"
        path.write_text(yaml_content, encoding="utf-8")

        loader = WorkflowLoader(workflows_dir=tmp_path)
        wf = loader.load("my_workflow")

        assert wf.name == "my_workflow"
        assert wf.description == "A test workflow"
        assert wf.config.model == "qwen-test"
        assert wf.config.max_tool_rounds == 2
        assert wf.parameters == {"topic": "AI"}
        assert len(wf.steps) == 1
        assert wf.steps[0].type == "task"
        assert wf.steps[0].name == "step1"
        assert wf.steps[0].enabled_tools == ["tool_a"]
        assert wf.steps[0].save_as == "result"

    def test_reject_missing_name(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("description: no name\nworkflow: []\n", encoding="utf-8")
        loader = WorkflowLoader(workflows_dir=tmp_path)
        with pytest.raises(ValueError, match="name"):
            loader.load("bad")

    def test_file_not_found(self, tmp_path):
        loader = WorkflowLoader(workflows_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent")

    def test_nested_steps_for_each(self, tmp_path):
        yaml_content = """
name: nested
workflow:
  - for_each:
      name: loop
      in: "items"
      item_var: "it"
      steps:
        - task:
            name: process
            instruction: "Process {{it}}"
            save_as: processed
"""
        path = tmp_path / "nested.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        loader = WorkflowLoader(workflows_dir=tmp_path)
        wf = loader.load("nested")
        assert wf.steps[0].type == "for_each"
        assert len(wf.steps[0].steps) == 1
        assert wf.steps[0].steps[0].type == "task"

    def test_nested_steps_if(self, tmp_path):
        yaml_content = """
name: conditional
workflow:
  - if:
      condition: "{{flag}}"
      then:
        - task:
            name: then_step
            instruction: "then"
      else:
        - task:
            name: else_step
            instruction: "else"
"""
        path = tmp_path / "conditional.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        loader = WorkflowLoader(workflows_dir=tmp_path)
        wf = loader.load("conditional")
        assert len(wf.steps[0].then_steps) == 1
        assert len(wf.steps[0].else_steps) == 1

    def test_template_var_extraction(self):
        vars_ = extract_template_vars("Search: {{topic}} with {{depth}}")
        assert vars_ == ["topic", "depth"]

    def test_set_variable_parsing(self, tmp_path):
        yaml_content = """
name: sv
workflow:
  - set_variable:
      output: "{{answer}}"
      status: "done"
"""
        path = tmp_path / "sv.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        loader = WorkflowLoader(workflows_dir=tmp_path)
        wf = loader.load("sv")
        step = wf.steps[0]
        assert step.type == "set_variable"
        assert step.variables == {"output": "{{answer}}", "status": "done"}

    def test_parse_agentspex_control_steps(self, tmp_path):
        yaml_content = """
name: agentspex
config:
  model_kwargs:
    temperature: 0.1
workflow:
  - increment:
      var: count
      by: 2
  - while:
      name: loop
      condition: count < 6
      max_iterations: 3
      steps:
        - increment:
            var: count
            by: 1
  - goto:
      target: done
  - parallel:
      name: fanout
      branches:
        - name: left
          steps:
            - set_variable:
                left: ok
        - name: right
          steps:
            - set_variable:
                right: ok
      save_as: parallel_results
  - call:
      workflow: child
      params:
        topic: "{{topic}}"
      save_as: child_result
  - submodule:
      workflow: child
      params:
        topic: "{{topic}}"
      save_as: submodule_result
  - set_variable:
      label: done
"""
        path = tmp_path / "agentspex.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        loader = WorkflowLoader(workflows_dir=tmp_path)
        wf = loader.load("agentspex")

        assert wf.config.model_kwargs == {"temperature": 0.1}
        assert [step.type for step in wf.steps] == [
            "increment", "while", "goto", "parallel", "call", "submodule", "set_variable",
        ]
        assert wf.steps[1].max_iterations == 3
        assert wf.steps[2].target == "done"
        assert [branch.name for branch in wf.steps[3].branches] == ["left", "right"]
        assert wf.steps[4].workflow == "child"
        assert wf.steps[5].workflow == "child"


# ---------------------------------------------------------------------------
# TestWorkflowContext
# ---------------------------------------------------------------------------

class TestWorkflowContext:
    def test_get_set_basic(self):
        ctx = WorkflowContext()
        ctx.set("key", "value")
        assert ctx.get("key") == "value"

    def test_dot_path_traversal(self):
        ctx = WorkflowContext({"a": {"b": {"c": 42}}})
        assert ctx.get("a.b.c") == 42
        assert ctx.get("a.b.x", "default") == "default"
        assert ctx.get("nonexistent") == ""

    def test_template_resolution(self):
        ctx = WorkflowContext({"topic": "AI", "count": 5})
        result = ctx.resolve("Search {{topic}} for top {{count}} papers")
        assert result == "Search AI for top 5 papers"

    def test_resolve_missing_var_becomes_empty(self):
        ctx = WorkflowContext()
        result = ctx.resolve("Hello {{name}}")
        assert result == "Hello "

    def test_resolve_nested_dict(self):
        ctx = WorkflowContext({"results": {"papers": 3, "source": "arxiv"}})
        result = ctx.resolve("Found {{results.papers}} papers from {{results.source}}")
        assert result == "Found 3 papers from arxiv"

    def test_as_bool(self):
        ctx = WorkflowContext({"flag1": True, "flag2": "yes", "flag3": 0, "flag4": [], "flag5": [1]})
        assert ctx.as_bool("flag1") is True
        assert ctx.as_bool("flag2") is True
        assert ctx.as_bool("flag3") is False
        assert ctx.as_bool("flag4") is False
        assert ctx.as_bool("flag5") is True

    def test_resolve_list_and_dict(self):
        ctx = WorkflowContext({"items": [1, 2, 3], "meta": {"key": "val"}})
        result_list = ctx.resolve("{{items}}")
        assert "[1, 2, 3]" in result_list
        result_dict = ctx.resolve("{{meta}}")
        assert '"key": "val"' in result_dict

    def test_condition_expression_supports_comparisons(self):
        ctx = WorkflowContext({"count": 2, "status": "ready"})
        assert ctx.eval_condition("count < 3") is True
        assert ctx.eval_condition("count >= 3") is False
        assert ctx.eval_condition("status == 'ready'") is True
        assert ctx.eval_condition("status != 'ready'") is False


# ---------------------------------------------------------------------------
# TestToolFiltering
# ---------------------------------------------------------------------------

class TestToolFiltering:
    def test_enabled_tools_whitelist(self):
        engine = WorkflowEngine()
        tools = engine._filter_tools(
            enabled=["academic_search_papers", "web_search"],
            disabled=[],
        )
        names = {t.name for t in tools}
        assert names == {"academic_search_papers", "web_search"}

    def test_disabled_tools_blacklist(self):
        engine = WorkflowEngine()
        all_names = {t.name for t in engine.tool_registry.get_tools_list()}
        tools = engine._filter_tools(
            enabled=[],
            disabled=["academic_search_papers", "web_search"],
        )
        names = {t.name for t in tools}
        assert "academic_search_papers" not in names
        assert "web_search" not in names
        assert len(names) == len(all_names) - 2

    def test_disabled_star_disables_all(self):
        engine = WorkflowEngine()
        tools = engine._filter_tools(enabled=[], disabled=["*"])
        assert tools == []

    def test_no_filter_returns_all(self):
        engine = WorkflowEngine()
        tools = engine._filter_tools(enabled=[], disabled=[])
        all_names = {t.name for t in engine.tool_registry.get_tools_list()}
        names = {t.name for t in tools}
        assert names == all_names


# ---------------------------------------------------------------------------
# TestStepHandlers (with mocked LLM)
# ---------------------------------------------------------------------------

class TestStepHandlers:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.engine = WorkflowEngine()

    def test_set_variable_step(self):
        ctx = WorkflowContext({"answer": "42"})
        step = StepDef(
            type="set_variable",
            variables={"output": "The answer is {{answer}}"},
        )
        self.engine._handle_set_variable(step, ctx)
        assert ctx.get("output") == "The answer is 42"

    def test_if_then_branch(self):
        ctx = WorkflowContext({"flag": "yes"})
        step = StepDef(
            type="if",
            condition="flag",
            then_steps=[StepDef(type="set_variable", variables={"result": "then"})],
            else_steps=[StepDef(type="set_variable", variables={"result": "else"})],
        )
        asyncio.run(self.engine._handle_if(step, ctx, None, 1))
        assert ctx.get("result") == "then"

    def test_if_else_branch(self):
        ctx = WorkflowContext({"flag": "no"})
        step = StepDef(
            type="if",
            condition="flag",
            then_steps=[StepDef(type="set_variable", variables={"result": "then"})],
            else_steps=[StepDef(type="set_variable", variables={"result": "else"})],
        )
        asyncio.run(self.engine._handle_if(step, ctx, None, 1))
        assert ctx.get("result") == "else"

    def test_for_each_iterates(self):
        ctx = WorkflowContext({"items": ["a", "b", "c"]})
        step = StepDef(
            type="for_each",
            in_ref="items",
            item_var="it",
            name="collected",
            steps=[
                StepDef(type="set_variable", variables={"upper": "{{it}}!"}),
            ],
        )
        asyncio.run(self.engine._handle_for_each(step, ctx, None, 1))
        collected = ctx.get("collected")
        assert isinstance(collected, list)
        assert len(collected) == 3
        assert collected[0]["upper"] == "a!"
        assert collected[2]["upper"] == "c!"

    def test_for_each_empty_list(self):
        ctx = WorkflowContext({"items": []})
        step = StepDef(
            type="for_each",
            in_ref="items",
            item_var="it",
            name="collected",
            steps=[StepDef(type="set_variable", variables={"x": "1"})],
        )
        asyncio.run(self.engine._handle_for_each(step, ctx, None, 1))
        collected = ctx.get("collected")
        assert collected == []

    def test_increment_step_adds_numeric_value(self):
        ctx = WorkflowContext({"count": 2})
        step = StepDef(type="increment", target="count", amount=3)
        self.engine._handle_increment(step, ctx)
        assert ctx.get("count") == 5

    def test_while_step_repeats_until_condition_is_false(self):
        ctx = WorkflowContext({"count": 0})
        step = StepDef(
            type="while",
            condition="count < 3",
            max_iterations=10,
            steps=[StepDef(type="increment", target="count", amount=1)],
        )
        asyncio.run(self.engine._handle_while(step, ctx, None, 1))
        assert ctx.get("count") == 3

    def test_parallel_step_runs_branches_and_saves_outputs(self):
        ctx = WorkflowContext({"seed": "s"})
        step = StepDef(
            type="parallel",
            name="fanout",
            save_as="branches",
            branches=[
                StepDef(
                    type="branch",
                    name="left",
                    steps=[StepDef(type="set_variable", variables={"value": "{{seed}}-left"})],
                ),
                StepDef(
                    type="branch",
                    name="right",
                    steps=[StepDef(type="set_variable", variables={"value": "{{seed}}-right"})],
                ),
            ],
        )
        asyncio.run(self.engine._handle_parallel(step, ctx, None, 1))
        assert ctx.get("branches.left.value") == "s-left"
        assert ctx.get("branches.right.value") == "s-right"

    def test_call_step_runs_nested_workflow_and_saves_result(self):
        child = WorkflowDef(
            name="child",
            parameters={"suffix": "default"},
            steps=[StepDef(type="set_variable", variables={"child_output": "{{topic}}-{{suffix}}"})],
        )
        engine = WorkflowEngine(workflows={"child": child})
        ctx = WorkflowContext({"topic": "agent"})
        step = StepDef(
            type="call",
            workflow="child",
            params={"topic": "{{topic}}", "suffix": "done"},
            save_as="child_result",
        )
        asyncio.run(engine._handle_call(step, ctx, None, 1))
        assert ctx.get("child_result.child_output") == "agent-done"

    def test_task_with_mock_llm_no_tools(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "The answer is 42."
        mock_response.tool_calls = []
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        ctx = WorkflowContext({"x": "question"})
        step = _task_step(instruction="Answer: {{x}}", save_as="out")
        asyncio.run(self.engine._handle_task(step, ctx, mock_llm, 3))

        assert ctx.get("out") == "The answer is 42."

    def test_task_with_mock_tool_loop(self):
        mock_llm = AsyncMock()
        # First response has tool calls
        resp1 = MagicMock()
        resp1.content = ""
        tc = MagicMock()
        tc.name = "get_current_time"
        tc.args = {"timezone": "UTC"}
        tc.id = "call_1"
        resp1.tool_calls = [tc]

        # Second response is final answer
        resp2 = MagicMock()
        resp2.content = "Done."
        resp2.tool_calls = []

        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=[resp1, resp2])

        ctx = WorkflowContext({"x": "test"})
        step = _task_step(instruction="Use tools: {{x}}", save_as="out")
        step.enabled_tools = ["get_current_time"]
        asyncio.run(self.engine._handle_task(step, ctx, mock_llm, 3))

        assert ctx.get("out") == "Done."


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_basic_workflow_with_set_variable(self):
        """End-to-end with only set_variable steps (no LLM needed)."""
        wf = WorkflowDef(
            name="test_wf",
            parameters={"topic": "AI"},
            steps=[
                StepDef(type="set_variable", variables={"greeting": "Hello {{topic}}"}),
                StepDef(type="set_variable", variables={"output": "{{greeting}}!"}),
            ],
        )
        engine = WorkflowEngine()
        result = asyncio.run(engine.run(wf))
        assert result["output"] == "Hello AI!"

    def test_goto_skips_to_named_step(self):
        wf = WorkflowDef(
            name="goto_wf",
            steps=[
                StepDef(type="set_variable", variables={"a": "1"}),
                StepDef(type="goto", target="finish"),
                StepDef(type="set_variable", variables={"skipped": "yes"}),
                StepDef(type="set_variable", name="finish", variables={"done": "yes"}),
            ],
        )
        engine = WorkflowEngine()
        result = asyncio.run(engine.run(wf))
        assert result["a"] == "1"
        assert "skipped" not in result
        assert result["done"] == "yes"

    def test_trace_records_step_events(self):
        wf = WorkflowDef(
            name="trace_wf",
            steps=[StepDef(type="set_variable", name="first", variables={"a": "1"})],
        )
        engine = WorkflowEngine()
        result = asyncio.run(engine.run(wf))
        trace = result["_trace"]
        assert trace[0]["event"] == "step_start"
        assert trace[0]["step"] == "first"
        assert trace[-1]["event"] == "step_end"

    def test_replay_trace_yields_recorded_events(self):
        trace = [
            {"event": "step_start", "step": "first", "type": "set_variable"},
            {"event": "step_end", "step": "first", "type": "set_variable"},
        ]
        events = list(WorkflowEngine.replay_trace(trace))
        assert events == [
            {"type": "replay", "index": 0, "event": trace[0]},
            {"type": "replay", "index": 1, "event": trace[1]},
        ]

    def test_stream_yields_events(self):
        async def _collect():
            events = []
            async for ev in engine.run_stream(wf):
                events.append(ev)
            return events

        wf = WorkflowDef(
            name="stream_test",
            steps=[
                StepDef(type="set_variable", variables={"a": "1"}),
                StepDef(type="set_variable", variables={"b": "2"}),
            ],
        )
        engine = WorkflowEngine()
        events = asyncio.run(_collect())

        event_types = [e["type"] for e in events]
        assert event_types == ["start", "step_start", "step_end",
                               "step_start", "step_end", "done"]


# ---------------------------------------------------------------------------
# TestRegression
# ---------------------------------------------------------------------------

class TestRegression:
    """Ensure the YAML engine imports don't break existing code."""

    def test_imports_dont_clash(self):
        from app.tools import tool_registry
        from app.services.workflow_loader import WorkflowLoader
        from app.services.workflow_engine import WorkflowEngine
        assert tool_registry.tool_count >= 10
