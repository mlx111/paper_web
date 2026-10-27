"""A local full-graph regression for provider thinking-message handoff."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def test_deepseek_thinking_plan_reaches_report_and_judge_without_protocol_loss(tmp_path):
    from agents import research_workflow_service as module

    seen = []

    class LocalThinkingModel(Runnable):
        provider = "deepseek"

        def bind_tools(self, tools):
            return self

        def invoke(self, messages, config=None, **kwargs):
            seen.append(messages)
            prompt = messages[0].content
            if "decide whether the user request" in prompt:
                content = json.dumps({"requires_research": True, "answer": None})
            elif "topic IS broad or ambiguous" in prompt:
                content = json.dumps({"needs_clarification": False, "candidates": [],
                                      "questions": [], "assumed_scope": "Agent papers", "refined_query": "Agent papers"})
            elif "step-by-step research plan" in prompt:
                content = "Research plan"
            elif "reviewing the final answer" in prompt:
                content = json.dumps({"is_good_answer": True, "feedback": None})
            else:
                plan = next(m for m in messages if isinstance(m, AIMessage) and m.name == "planning")
                assert plan.additional_kwargs["reasoning_content"] == "planning thoughts"
                content = "Research report with citation [1]."
            return AIMessage(content=content, additional_kwargs={"reasoning_content": "planning thoughts"})

    with patch.object(module.qwen_model, "init_model", return_value=LocalThinkingModel()):
        service = module.ResearchWorkflowService()
    service.artifact_root = tmp_path / "artifacts"
    service.history_root = tmp_path / "history"
    service._gather_branch_sources = lambda branches, refined_query: branches
    service._enrich_with_entity_graph = lambda branches, seen_titles: None
    service._rank_branch_sources = lambda branches, refined_query: None
    result = service.workflow.compile().invoke({"messages": [HumanMessage(content="Find Agent papers")]})

    assert result["is_good_answer"] is True
    assert any(m.name == "agent" for m in result["messages"] if isinstance(m, AIMessage))
    assert len(seen) >= 5


def test_research_tool_round_limit_does_not_send_unexecuted_calls_to_judge(tmp_path):
    from agents import research_workflow_service as module

    @tool("probe")
    def probe() -> str:
        """Return a small test result."""
        return "tool result"

    class PlainModel(Runnable):
        provider = "deepseek"

        def bind_tools(self, tools):
            return self

        def invoke(self, messages, config=None, **kwargs):
            return AIMessage(content="Final report")

    class BoundAgent:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages, config=None, **kwargs):
            self.calls += 1
            return AIMessage(
                content="",
                tool_calls=[{"id": f"call-{self.calls}", "name": "probe", "args": {}}],
            )

    class FixedResult:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Judge:
        def invoke(self, messages, config=None, **kwargs):
            for index, message in enumerate(messages):
                calls = getattr(message, "tool_calls", []) or []
                if not calls:
                    continue
                expected = {call["id"] for call in calls}
                actual = {
                    getattr(item, "tool_call_id", "")
                    for item in messages[index + 1:index + 1 + len(expected)]
                    if isinstance(item, ToolMessage)
                }
                assert actual == expected, "judge received an incomplete tool-call round"
            return FixedResult(is_good_answer=True, feedback=None)

    with patch.object(module.qwen_model, "init_model", return_value=PlainModel()):
        service = module.ResearchWorkflowService()
    agent = BoundAgent()
    service.model = PlainModel()
    service.agent_llm = agent
    service.decision_llm = type("Decision", (), {"invoke": lambda self, *_a, **_k: FixedResult(requires_research=True, answer=None)})()
    service.clarify_llm = type("Clarify", (), {"invoke": lambda self, *_a, **_k: FixedResult(
        needs_clarification=False, candidates=[], questions=[], assumed_scope="scope", refined_query="topic"
    )})()
    service.judge_llm = Judge()
    service.artifact_root = tmp_path / "artifacts"
    service.history_root = tmp_path / "history"
    service._gather_branch_sources = lambda branches, refined_query: branches
    service._enrich_with_entity_graph = lambda branches, seen_titles: None
    service._rank_branch_sources = lambda branches, refined_query: None

    with patch.object(module, "TOOLS", [probe]):
        result = service.workflow.compile().invoke({"messages": [HumanMessage(content="research topic")]})

    assert result["is_good_answer"] is True
    assert agent.calls == 3
    assert any(isinstance(message, AIMessage) and message.content == "Final report" for message in result["messages"])


def test_research_stream_does_not_expose_raw_tool_results():
    from agents.research_workflow_service import ResearchWorkflowService

    tool_result = ToolMessage(
        name="get_paper_abstract",
        tool_call_id="call-1",
        content='{"ok": true, "data": {"abstract": "private evidence"}}',
    )

    assert ResearchWorkflowService._stream_message_events("tools", tool_result) == []
