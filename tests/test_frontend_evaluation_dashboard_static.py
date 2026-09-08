from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_dashboard_component_contains_required_sections():
    component = ROOT / "frontend" / "src" / "components" / "EvaluationDashboard.vue"

    text = component.read_text(encoding="utf-8")

    assert "defineEmits(['open-trace'])" in text
    assert "failureCategories" in text
    assert "failedCases" in text
    assert "runBenchmark" in text
    assert "token_usage" in text
    assert "查看 Trace" in text


def test_frontend_api_exposes_evaluation_methods():
    api = (ROOT / "frontend" / "src" / "services" / "api.js").read_text(encoding="utf-8")

    assert "export async function listEvaluationReports" in api
    assert "export async function getEvaluationReport" in api
    assert "export async function runEvaluation" in api
    assert "/evaluation/reports" in api
    assert "/evaluation/run" in api


def test_app_registers_evaluation_module_and_dashboard():
    app_vue = (ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "EvaluationDashboard" in app_vue
    assert "key: 'evaluation'" in app_vue
    assert "utility: true" in app_vue
    assert "activeModule === 'evaluation'" in app_vue


def test_sidebar_hides_chat_controls_for_utility_modules():
    sidebar = (ROOT / "frontend" / "src" / "components" / "Sidebar.vue").read_text(encoding="utf-8")

    assert "activeModuleConfig" in sidebar
    assert "showChatControls" in sidebar
    assert 'v-if="showChatControls"' in sidebar
