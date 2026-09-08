from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def read_frontend(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_workflow_api_helpers_are_exported():
    source = read_frontend("services/api.js")

    assert "export async function runWorkflowStream" in source
    assert "export async function getWorkflowProgress" in source
    assert "export async function clearWorkflowCheckpoints" in source
    assert "/workflow/run_stream" in source
    assert "/workflow/progress" in source


def test_workflow_metadata_is_preserved_in_messages():
    source = read_frontend("utils/session.js")

    assert "workflowRunId:" in source
    assert "workflowName:" in source
    assert "workflowStatus:" in source
    assert "workflowSteps:" in source


def test_workflow_panel_component_and_app_integration_exist():
    assert (FRONTEND / "components" / "WorkflowPanel.vue").exists()

    app_source = read_frontend("App.vue")
    panel_source = read_frontend("components/WorkflowPanel.vue")

    assert "WorkflowPanel" in app_source
    assert "runResearchWorkflow" in app_source
    assert "resumeWorkflow" in app_source
    assert "workflowName: 'research_simple'" in app_source
    assert "工作流进度" in panel_source
    assert "从失败步骤继续" in panel_source
    assert "workflow-step-card" in panel_source


def test_vite_proxies_workflow_api_to_backend():
    source = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")

    assert '"/workflow"' in source
