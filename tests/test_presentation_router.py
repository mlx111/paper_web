import importlib
import sys
import types
import unittest
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    FastAPI = None
    TestClient = None


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _fake_service():
    async def _fake_stream_events(request):
        yield {"type": "debug", "data": "classify"}
        yield {"type": "complete", "data": {"pptx_path": f"{request.session_id}/output.pptx"}}

    return types.SimpleNamespace(
        run_topic=lambda session_id, topic, target_pages=None: {
            "answer": f"{topic} done",
            "plan_path": f"{session_id}/plan.json",
            "manuscript_path": f"{session_id}/manuscript.md",
            "pptx_path": f"{session_id}/output.pptx",
        },
        query_stream=lambda request: _fake_stream_events(request),
        clear_session=lambda session_id: True,
        get_session_history=lambda session_id: [],
    )


@unittest.skipUnless(FastAPI is not None and TestClient is not None, "fastapi is not installed")
class PresentationRouterTest(unittest.TestCase):
    def setUp(self):
        self.original_loguru = sys.modules.get("loguru")
        self.original_service_module = sys.modules.get("agents.presentation_workflow_service")

        sys.modules["loguru"] = types.ModuleType("loguru")
        sys.modules["loguru"].logger = types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        )

        fake_module = types.ModuleType("agents.presentation_workflow_service")
        fake_module.presentation_workflow_service = _fake_service()
        sys.modules["agents.presentation_workflow_service"] = fake_module
        sys.modules.pop("routers.presentation", None)

    def tearDown(self):
        if self.original_loguru is None:
            sys.modules.pop("loguru", None)
        else:
            sys.modules["loguru"] = self.original_loguru

        if self.original_service_module is None:
            sys.modules.pop("agents.presentation_workflow_service", None)
        else:
            sys.modules["agents.presentation_workflow_service"] = self.original_service_module

        sys.modules.pop("routers.presentation", None)

    def test_presentation_router_exposes_chat_endpoint(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.post(
            "/presentation/chat",
            json={"sessionId": "presentation-123", "topic": "Enterprise RAG overview"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)

    def test_presentation_stream_emits_progress_events(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        with client.stream(
            "POST",
            "/presentation/chat_stream",
            json={"sessionId": "presentation-123", "topic": "Enterprise RAG overview"},
        ) as response:
            body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "debug"', body)
        self.assertIn('"type": "done"', body)


if __name__ == "__main__":
    unittest.main()
