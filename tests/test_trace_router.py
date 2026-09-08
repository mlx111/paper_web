import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class _FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _FakeAPIRouter:
    def __init__(self, *args, **kwargs):
        self.routes = []

    def get(self, path):
        def decorator(func):
            self.routes.append(("GET", path, func))
            return func

        return decorator


@pytest.fixture(autouse=True)
def fake_fastapi_module():
    original = sys.modules.get("fastapi")
    fake = types.ModuleType("fastapi")
    fake.APIRouter = _FakeAPIRouter
    fake.HTTPException = _FakeHTTPException
    sys.modules["fastapi"] = fake
    sys.modules.pop("routers.trace", None)
    yield
    sys.modules.pop("routers.trace", None)
    if original is None:
        sys.modules.pop("fastapi", None)
    else:
        sys.modules["fastapi"] = original


def _router_with_trace(tmp_path):
    from services.run_trace_service import RunTraceService

    service = RunTraceService(base_dir=tmp_path)
    run = service.start_run(
        session_id="session-1",
        route="deep",
        question="what is agentic rag?",
    )
    with service.step(run.run_id, "context_build", "context") as step:
        step.set_output({"context_mode": "deep", "evidence_count": 2})
    service.end_run(run.run_id, status="completed")

    router_module = importlib.import_module("routers.trace")
    router_module.trace_service = service
    return router_module, run.run_id


def test_get_trace_by_run_id(tmp_path):
    router_module, run_id = _router_with_trace(tmp_path)

    response = asyncio.run(router_module.get_trace(run_id))

    assert response["code"] == 200
    assert response["data"]["run_id"] == run_id
    assert response["data"]["status"] == "completed"
    assert response["data"]["steps"][0]["step_name"] == "context_build"


def test_get_trace_summary_by_run_id(tmp_path):
    router_module, run_id = _router_with_trace(tmp_path)

    response = asyncio.run(router_module.get_trace_summary(run_id))

    assert response["code"] == 200
    assert response["data"]["trace_status"] == "completed"
    assert response["data"]["step_count"] == 1


def test_get_trace_replay_by_run_id(tmp_path):
    router_module, run_id = _router_with_trace(tmp_path)

    response = asyncio.run(router_module.get_trace_replay(run_id))

    assert response["code"] == 200
    assert response["data"]["run_id"] == run_id
    assert response["data"]["question"] == "what is agentic rag?"
    assert response["data"]["summary"]["step_count"] == 1
    assert response["data"]["steps"][0]["step_name"] == "context_build"


def test_list_traces_by_session_id(tmp_path):
    router_module, run_id = _router_with_trace(tmp_path)

    response = asyncio.run(router_module.list_traces(session_id="session-1"))

    assert response["code"] == 200
    assert response["data"]["count"] == 1
    assert response["data"]["runs"][0]["run_id"] == run_id


def test_missing_trace_returns_404(tmp_path):
    router_module, _ = _router_with_trace(tmp_path)

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(router_module.get_trace("missing-run"))

    assert exc_info.value.status_code == 404


def test_missing_trace_summary_returns_404(tmp_path):
    router_module, _ = _router_with_trace(tmp_path)

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(router_module.get_trace_summary("missing-run"))

    assert exc_info.value.status_code == 404


def test_missing_trace_replay_returns_404(tmp_path):
    router_module, _ = _router_with_trace(tmp_path)

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(router_module.get_trace_replay("missing-run"))

    assert exc_info.value.status_code == 404
