from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def read_frontend(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_trace_panel_has_tool_step_summary_ui():
    source = read_frontend("components/TracePanel.vue")

    assert "isToolStep" in source
    assert "trace-tool-card" in source
    assert "toolSummary" in source
    assert "error_code" in source
    assert "data_size" in source
