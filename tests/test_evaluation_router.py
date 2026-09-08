import json
import sys
import types
import asyncio
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

fastapi_stub = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class APIRouter:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return lambda fn: fn

    def post(self, *args, **kwargs):
        return lambda fn: fn


fastapi_stub.APIRouter = APIRouter
fastapi_stub.HTTPException = HTTPException
sys.modules.setdefault("fastapi", fastapi_stub)

from routers import evaluation as evaluation_router


def test_lists_evaluation_reports_from_reports_dir(tmp_path, monkeypatch):
    report_path = tmp_path / "report-a.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "total_cases": 2,
                    "passed_cases": 1,
                    "failure_categories": {"tool_error": 1},
                },
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(evaluation_router, "REPORTS_DIR", tmp_path)

    response = asyncio.run(evaluation_router.list_evaluation_reports())

    assert response["code"] == 200
    payload = response["data"]
    assert payload["count"] == 1
    assert payload["reports"][0]["name"] == "report-a.json"
    assert payload["reports"][0]["summary"]["total_cases"] == 2
    assert payload["reports"][0]["summary"]["failure_categories"] == {"tool_error": 1}


def test_gets_evaluation_report_by_name(tmp_path, monkeypatch):
    report_path = tmp_path / "report-a.json"
    report = {
        "summary": {"total_cases": 1, "passed_cases": 1},
        "results": [{"case_id": "case-1", "run_id": "run-1"}],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(evaluation_router, "REPORTS_DIR", tmp_path)

    response = asyncio.run(evaluation_router.get_evaluation_report("report-a.json"))

    assert response["code"] == 200
    assert response["data"]["results"][0]["run_id"] == "run-1"


def test_rejects_evaluation_report_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation_router, "REPORTS_DIR", tmp_path)

    try:
        asyncio.run(evaluation_router.get_evaluation_report("../secret.json"))
    except HTTPException as exc:
        assert exc.status_code in (400, 404)
    else:
        raise AssertionError("path traversal should be rejected")


def test_run_evaluation_writes_timestamped_reports(tmp_path, monkeypatch):
    class FakeSummary:
        total_cases = 1
        passed_cases = 1
        route_accuracy = 1.0
        tool_accuracy = 1.0
        tool_args_accuracy = 1.0
        keyword_hit_rate = 1.0
        evidence_hit_rate = 1.0
        avg_latency_ms = 12.0
        avg_score = 1.0
        failed_cases = []

    class FakeRunner:
        def __init__(self, cases_path):
            self.cases_path = cases_path

        async def run(self):
            return [], FakeSummary()

    monkeypatch.setattr(evaluation_router, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(evaluation_router, "EvaluationRunner", FakeRunner)

    response = asyncio.run(evaluation_router.run_evaluation())

    assert response["code"] == 200
    data = response["data"]
    assert data["report_name"].startswith("report-")
    assert data["report_name"].endswith(".json")
    assert (tmp_path / data["report_name"]).exists()
    assert (tmp_path / data["markdown_name"]).exists()
    assert data["summary"]["total_cases"] == 1


def test_run_mcp_evaluation_writes_mcp_report(tmp_path, monkeypatch):
    class FakeMCPEvaluationRunner:
        def __init__(self, cases_path):
            self.cases_path = cases_path

        async def run(self):
            class FakeSummary:
                total_cases = 1
                passed_cases = 1
                route_accuracy = 1.0
                tool_accuracy = 1.0
                tool_args_accuracy = 1.0
                keyword_hit_rate = 1.0
                evidence_hit_rate = 1.0
                avg_latency_ms = 1.0
                avg_score = 1.0
                failed_cases = []

            return [], FakeSummary()

    module = types.ModuleType("evaluation.mcp_runner")
    module.MCPEvaluationRunner = FakeMCPEvaluationRunner
    monkeypatch.setitem(sys.modules, "evaluation.mcp_runner", module)
    monkeypatch.setattr(evaluation_router, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(evaluation_router, "MCP_CASES_PATH", tmp_path / "mcp_cases.json")

    response = asyncio.run(evaluation_router.run_mcp_evaluation())

    data = response["data"]
    assert data["report_name"].startswith("mcp-report-")
    assert data["report_name"].endswith(".json")
    assert data["markdown_name"].startswith("mcp-report-")
    assert (tmp_path / data["report_name"]).exists()
    report = json.loads((tmp_path / data["report_name"]).read_text(encoding="utf-8"))
    assert report["summary"]["total_cases"] == 1
