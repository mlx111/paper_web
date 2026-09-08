import pytest

from services.run_trace_service import RunTraceService


def test_records_successful_step(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(
        session_id="session-1",
        route="deep",
        question="what is agentic rag?",
    )

    with service.step(run.run_id, "context_build", "context") as step:
        step.set_input({"top_k": 8})
        step.set_output({"evidence_count": 3})

    loaded = service.load_run(run.run_id)

    assert loaded["run_id"] == run.run_id
    assert loaded["session_id"] == "session-1"
    assert loaded["status"] == "running"
    assert loaded["steps"][0]["step_name"] == "context_build"
    assert loaded["steps"][0]["step_type"] == "context"
    assert loaded["steps"][0]["status"] == "completed"
    assert loaded["steps"][0]["input"] == {"top_k": 8}
    assert loaded["steps"][0]["output"] == {"evidence_count": 3}
    assert loaded["steps"][0]["latency_ms"] >= 0


def test_records_failed_step_and_reraises(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(session_id="session-1", route="deep", question="boom")

    with pytest.raises(ValueError, match="bad context"):
        with service.step(run.run_id, "context_build", "context"):
            raise ValueError("bad context")

    loaded = service.load_run(run.run_id)

    assert loaded["steps"][0]["status"] == "failed"
    assert loaded["steps"][0]["error"] == "bad context"
    assert loaded["steps"][0]["ended_at"] is not None


def test_end_run_persists_failed_status_and_error(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(session_id="session-1", route="quick", question="fail")

    service.end_run(run.run_id, status="failed", error="model timeout")
    loaded = service.load_run(run.run_id)

    assert loaded["status"] == "failed"
    assert loaded["error"] == "model timeout"
    assert loaded["ended_at"] is not None


def test_lists_runs_by_session(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run_a = service.start_run(session_id="session-a", route="deep", question="a")
    service.start_run(session_id="session-b", route="quick", question="b")

    runs = service.list_runs(session_id="session-a")

    assert [run["run_id"] for run in runs] == [run_a.run_id]


def test_summarize_run_collects_latency_tools_and_failures(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(session_id="session-1", route="mcp", question="q")

    with service.step(run.run_id, "context_build", "context") as step:
        step.set_output({"ok": True})

    with service.step(run.run_id, "mcp:mypaper_web_search", "mcp_tool") as step:
        step.set_output({"ok": False, "error_code": "TOOL_TIMEOUT"})
        step.mark_failed("timeout")

    service.end_run(run.run_id, status="failed", error="timeout")

    summary = service.summarize_run(run.run_id)
    loaded = service.load_run(run.run_id)

    assert summary["trace_status"] == "failed"
    assert summary["step_count"] == 2
    assert summary["failed_steps"] == ["mcp:mypaper_web_search"]
    assert summary["tool_steps"] == ["mcp:mypaper_web_search"]
    assert summary["mcp_tool_steps"] == ["mcp:mypaper_web_search"]
    assert summary["tool_error_codes"] == ["TOOL_TIMEOUT"]
    assert summary["total_latency_ms"] >= 0
    assert summary["error"] == "timeout"
    assert loaded["summary"] == summary


def test_build_replay_exports_trace_without_rerunning_steps(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(session_id="session-1", route="deep", question="q")

    with service.step(run.run_id, "tool:web_search", "tool") as step:
        step.set_input({"query": "agent"})
        step.set_output({"summary": "ok"})

    service.end_run(run.run_id, status="completed")

    replay = service.build_replay(run.run_id)

    assert replay["run_id"] == run.run_id
    assert replay["session_id"] == "session-1"
    assert replay["route"] == "deep"
    assert replay["question"] == "q"
    assert replay["status"] == "completed"
    assert replay["summary"]["tool_steps"] == ["tool:web_search"]
    assert replay["steps"][0]["input"] == {"query": "agent"}
    assert replay["steps"][0]["output"] == {"summary": "ok"}


def test_step_input_and_output_redact_sensitive_fields(tmp_path):
    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(session_id="session-1", route="deep", question="q")

    with service.step(run.run_id, "tool:web_search", "tool") as step:
        step.set_input(
            {
                "query": "agent",
                "api_key": "secret-key",
                "nested": {
                    "token": "abc",
                    "count": 3,
                },
            }
        )
        step.set_output(
            {
                "result": "ok",
                "authorization": "Bearer secret",
                "items": [
                    {
                        "password": "pw",
                        "title": "paper",
                    }
                ],
            }
        )

    loaded = service.load_run(run.run_id)
    recorded = loaded["steps"][0]

    assert recorded["input"]["query"] == "agent"
    assert recorded["input"]["api_key"] == "***"
    assert recorded["input"]["nested"]["token"] == "***"
    assert recorded["input"]["nested"]["count"] == 3
    assert recorded["output"]["result"] == "ok"
    assert recorded["output"]["authorization"] == "***"
    assert recorded["output"]["items"][0]["password"] == "***"
    assert recorded["output"]["items"][0]["title"] == "paper"
