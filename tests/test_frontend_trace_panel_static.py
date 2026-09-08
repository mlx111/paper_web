from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def read_frontend(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_trace_api_helpers_are_exported():
    source = read_frontend("services/api.js")

    assert "export async function getTrace" in source
    assert "export async function listTraces" in source
    assert "/traces/" in source


def test_trace_metadata_is_preserved_in_messages():
    source = read_frontend("utils/session.js")

    assert "runId:" in source
    assert "tracePath:" in source
    assert "traceStatus:" in source


def test_trace_panel_component_and_app_integration_exist():
    assert (FRONTEND / "components" / "TracePanel.vue").exists()

    app_source = read_frontend("App.vue")
    chat_window_source = read_frontend("components/ChatWindow.vue")
    chat_message_source = read_frontend("components/ChatMessage.vue")

    assert "TracePanel" in app_source
    assert "handleOpenTrace" in app_source
    assert "payload.type === 'context'" in app_source
    assert "run_id" in app_source
    assert "open-trace" in chat_window_source
    assert "open-trace" in chat_message_source


def test_trace_button_status_and_auto_refresh_are_wired():
    app_source = read_frontend("App.vue")
    chat_message_source = read_frontend("components/ChatMessage.vue")
    trace_panel_source = read_frontend("components/TracePanel.vue")

    assert "maybeRefreshOpenTrace" in app_source
    assert "traceStatus: 'running'" in app_source
    assert "traceStatus: 'completed'" in app_source
    assert "traceStatus: 'failed'" in app_source
    assert "traceButtonLabel" in chat_message_source
    assert "Trace 生成中" in chat_message_source
    assert "查看 Trace" in chat_message_source
    assert "查看失败 Trace" in chat_message_source
    assert "trace-running-notice" in trace_panel_source


def test_trace_panel_supports_chinese_english_and_token_usage():
    source = read_frontend("components/TracePanel.vue")

    assert "运行追踪" in source
    assert "Run Trace" in source
    assert "Token 消耗" in source
    assert "Token Usage" in source
    assert "token_usage" in source
    assert "estimated" in source


def test_trace_panel_displays_run_summary_fields():
    source = read_frontend("components/TracePanel.vue")

    assert "trace.summary" in source
    assert "failed_steps" in source
    assert "tool_steps" in source
    assert "mcp_tool_steps" in source
    assert "tool_error_codes" in source
    assert "Failed Steps" in source
    assert "MCP Tools" in source
    assert "Error Codes" in source


def test_vite_proxies_trace_api_to_backend():
    source = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")

    assert '"/traces"' in source
