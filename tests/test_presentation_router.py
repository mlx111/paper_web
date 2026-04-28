import importlib
import sys
import tempfile
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


def _fake_service(temp_root: Path):
    async def _fake_stream_events(request):
        yield {"type": "debug", "data": "classify"}
        yield {
            "type": "complete",
            "data": {
                "answer": "done",
                "pptx_path": f"{request.session_id}/output.pptx",
                "artifacts": {
                    "pptx_path": f"{request.session_id}/output.pptx",
                    "download_urls": {
                        "pptx": f"/presentation/download/{request.session_id}/pptx",
                        "plan": f"/presentation/download/{request.session_id}/plan",
                        "manuscript": f"/presentation/download/{request.session_id}/manuscript",
                    },
                },
            },
        }

    def _build_artifact_paths(session_id: str):
        session_dir = temp_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        outline_path = session_dir / "outline.json"
        layout_path = session_dir / "layout.json"
        schema_path = session_dir / "schema.json"
        design_path = session_dir / "design.json"
        plan_path = session_dir / "plan.json"
        manuscript_path = session_dir / "manuscript.md"
        pptx_path = session_dir / "output.pptx"
        manifest_path = session_dir / "artifact_manifest.json"
        quality_path = session_dir / "quality_report.json"
        history_path = session_dir / "history.json"
        outline_path.write_text("{}", encoding="utf-8")
        layout_path.write_text("{}", encoding="utf-8")
        schema_path.write_text("{}", encoding="utf-8")
        design_path.write_text("{}", encoding="utf-8")
        plan_path.write_text("{}", encoding="utf-8")
        manuscript_path.write_text("# Slide", encoding="utf-8")
        pptx_path.write_bytes(b"pptx-bytes")
        manifest_path.write_text("{}", encoding="utf-8")
        quality_path.write_text("{}", encoding="utf-8")
        return {
            "session_dir": session_dir,
            "outline_path": outline_path,
            "layout_path": layout_path,
            "schema_path": schema_path,
            "design_path": design_path,
            "plan_path": plan_path,
            "manuscript_path": manuscript_path,
            "pptx_path": pptx_path,
            "artifact_manifest_path": manifest_path,
            "quality_report_path": quality_path,
            "history_path": history_path,
        }

        return types.SimpleNamespace(
            run_topic=lambda session_id, topic, target_pages=None, research_session_id=None: {
                "answer": f"{topic} done",
                "outline_path": f"{session_id}/outline.json",
                "layout_path": f"{session_id}/layout.json",
                "schema_path": f"{session_id}/schema.json",
                "design_path": f"{session_id}/design.json",
                "plan_path": f"{session_id}/plan.json",
                "manuscript_path": f"{session_id}/manuscript.md",
                "pptx_path": f"{session_id}/output.pptx",
                "artifacts": {
                    "outline_path": f"{session_id}/outline.json",
                    "layout_path": f"{session_id}/layout.json",
                    "schema_path": f"{session_id}/schema.json",
                    "design_path": f"{session_id}/design.json",
                    "quality_report_path": f"{session_id}/quality_report.json",
                    "plan_path": f"{session_id}/plan.json",
                    "manuscript_path": f"{session_id}/manuscript.md",
                    "pptx_path": f"{session_id}/output.pptx",
                    "manifest_path": f"{session_id}/artifact_manifest.json",
                    "download_urls": {
                        "pptx": f"/presentation/download/{session_id}/pptx",
                        "plan": f"/presentation/download/{session_id}/plan",
                        "manuscript": f"/presentation/download/{session_id}/manuscript",
                        "outline": f"/presentation/download/{session_id}/outline",
                        "layout": f"/presentation/download/{session_id}/layout",
                        "schema": f"/presentation/download/{session_id}/schema",
                        "design": f"/presentation/download/{session_id}/design",
                        "quality": f"/presentation/download/{session_id}/quality",
                    },
                    "quality_report": {"passed": True, "issues": [], "warnings": [], "quality_report_path": f"{session_id}/quality_report.json"},
                },
            },
        query_stream=lambda request: _fake_stream_events(request),
        clear_session=lambda session_id: True,
        get_session_history=lambda session_id: [],
        check_quality=lambda session_id: {
            "session_id": session_id,
            "passed": True,
            "issues": [],
            "warnings": [],
            "quality_report_path": f"{session_id}/quality_report.json",
        },
        regenerate_from_artifacts=lambda session_id: {
            "answer": "regenerated",
            "artifacts": {
                "outline_path": f"{session_id}/outline.json",
                "layout_path": f"{session_id}/layout.json",
                "schema_path": f"{session_id}/schema.json",
                "design_path": f"{session_id}/design.json",
                "quality_report_path": f"{session_id}/quality_report.json",
                "plan_path": f"{session_id}/plan.json",
                "manuscript_path": f"{session_id}/manuscript.md",
                "pptx_path": f"{session_id}/output.pptx",
                "manifest_path": f"{session_id}/artifact_manifest.json",
                "download_urls": {
                    "pptx": f"/presentation/download/{session_id}/pptx",
                    "plan": f"/presentation/download/{session_id}/plan",
                    "manuscript": f"/presentation/download/{session_id}/manuscript",
                    "outline": f"/presentation/download/{session_id}/outline",
                    "layout": f"/presentation/download/{session_id}/layout",
                    "schema": f"/presentation/download/{session_id}/schema",
                    "design": f"/presentation/download/{session_id}/design",
                    "quality": f"/presentation/download/{session_id}/quality",
                },
            },
        },
        _build_artifact_paths=_build_artifact_paths,
    )


@unittest.skipUnless(FastAPI is not None and TestClient is not None, "fastapi is not installed")
class PresentationRouterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_loguru = sys.modules.get("loguru")
        self.original_service_module = sys.modules.get("agents.presentation_workflow_service")

        sys.modules["loguru"] = types.ModuleType("loguru")
        sys.modules["loguru"].logger = types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        )

        fake_module = types.ModuleType("agents.presentation_workflow_service")
        fake_module.presentation_workflow_service = _fake_service(self.temp_dir)
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

        for path in sorted(self.temp_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

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
        body = response.json()
        self.assertEqual(body["code"], 200)
        self.assertIn("artifacts", body["data"])
        self.assertIn("download_urls", body["data"]["artifacts"])

    def test_presentation_download_route_serves_pptx(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.get("/presentation/download/presentation-123/pptx")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-disposition"].split("filename=")[-1].strip('"'), "output.pptx")
        self.assertEqual(response.content, b"pptx-bytes")

    def test_presentation_download_route_serves_design(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.get("/presentation/download/presentation-123/design")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-disposition"].split("filename=")[-1].strip('"'), "design.json")
        self.assertEqual(response.text, "{}")

    def test_presentation_download_route_serves_outline(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.get("/presentation/download/presentation-123/outline")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-disposition"].split("filename=")[-1].strip('"'), "outline.json")
        self.assertEqual(response.text, "{}")

    def test_presentation_download_route_serves_quality_report(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.get("/presentation/download/presentation-123/quality")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-disposition"].split("filename=")[-1].strip('"'), "quality_report.json")
        self.assertEqual(response.text, "{}")

    def test_presentation_quality_route_checks_saved_artifacts(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.post("/presentation/quality", json={"sessionId": "presentation-123"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 200)
        self.assertTrue(body["data"]["passed"])

    def test_presentation_regenerate_route_rebuilds_saved_artifacts(self):
        router_module = importlib.import_module("routers.presentation")

        app = FastAPI()
        app.include_router(router_module.router)
        client = TestClient(app)

        response = client.post("/presentation/regenerate", json={"sessionId": "presentation-123"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 200)
        self.assertEqual(body["data"]["answer"], "regenerated")

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
