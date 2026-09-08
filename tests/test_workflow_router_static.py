from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_router_does_not_store_run_trace_state_on_global_engine():
    source = (ROOT / "app" / "routers" / "workflow.py").read_text(encoding="utf-8")

    assert "_engine.trace_service =" not in source
    assert "_engine.trace_run_id =" not in source
    assert "_engine = WorkflowEngine()" not in source
    assert "WorkflowEngine()" in source
