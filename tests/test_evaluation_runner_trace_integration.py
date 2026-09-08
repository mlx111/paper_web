import asyncio
import sys
import types


agents_pkg = sys.modules.setdefault("agents", types.ModuleType("agents"))
deep_module = types.ModuleType("agents.deep_agent_service")
quick_module = types.ModuleType("agents.quick_agent_service")
deep_module.deep_agent_service = object()
quick_module.quick_agent_service = object()
sys.modules.setdefault("agents.deep_agent_service", deep_module)
sys.modules.setdefault("agents.quick_agent_service", quick_module)

from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import EvaluationCase


class FakeAgent:
    context_mode = "deep"

    async def query_stream(self, question, session_id):
        yield {
            "type": "context",
            "data": {
                "context_mode": "deep",
                "trace": {"evidence_count": 1},
                "run_id": "run-123",
                "trace_path": "runtime/run_traces/case-1/run-123.json",
            },
        }
        yield {"type": "tool_call", "data": {"tool_name": "web_search", "arguments": {"query": "agent"}}}
        yield {"type": "content", "data": "answer without required keyword"}
        yield {"type": "complete"}


class FakeTraceService:
    def load_run(self, run_id):
        assert run_id == "run-123"
        return {
            "run_id": run_id,
            "status": "completed",
            "steps": [
                {
                    "step_name": "model_stream",
                    "step_type": "model",
                    "status": "completed",
                    "latency_ms": 11,
                    "output": {"token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
                },
                {
                    "step_name": "tool:web_search",
                    "step_type": "tool",
                    "status": "failed",
                    "latency_ms": 7,
                    "error": "timeout",
                    "output": {"error_code": "TOOL_TIMEOUT"},
                },
            ],
        }


def test_runner_attaches_trace_summary_and_failure_category(monkeypatch):
    import app.evaluation.runner as runner_module

    monkeypatch.setattr(runner_module, "get_target_agent", lambda mode: FakeAgent())
    monkeypatch.setattr(runner_module, "default_run_trace_service", FakeTraceService())

    case = EvaluationCase(
        id="case-1",
        question="question",
        mode="deep",
        expected_route="quick",
        expected_tools=["web_search"],
        expected_tool_args={"web_search": {"query": "agent"}},
        must_include=["required term"],
    )

    result = asyncio.run(EvaluationRunner("unused.json")._run_one(case))

    assert result.run_id == "run-123"
    assert result.trace_path == "runtime/run_traces/case-1/run-123.json"
    assert result.token_usage == 15
    assert result.trace_summary["trace_status"] == "completed"
    assert result.trace_summary["step_count"] == 2
    assert result.trace_summary["tool_steps"] == ["tool:web_search"]
    assert result.trace_summary["tool_error_codes"] == ["TOOL_TIMEOUT"]
    assert result.failure_category == "tool_error"
    assert "TOOL_TIMEOUT" in result.failure_reason
