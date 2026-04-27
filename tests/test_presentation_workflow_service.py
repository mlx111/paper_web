import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

STUB_MODULES = [
    "langchain_core.messages",
    "langchain_core.tools",
    "langgraph.graph",
    "langgraph.graph.message",
    "loguru",
    "models.factory",
    "tools.websearch_tool",
]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in STUB_MODULES}

for name in STUB_MODULES:
    sys.modules.setdefault(name, types.ModuleType(name))

sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
sys.modules["models.factory"].qwen_model = types.SimpleNamespace(
    init_model=lambda streaming=False: None
)
sys.modules["tools.websearch_tool"].web_search = lambda query, **kwargs: []


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class PresentationRequestTest(unittest.TestCase):
    def test_presentation_request_accepts_topic_and_optional_fields(self):
        from models.request import PresentationRequest

        request = PresentationRequest(
            sessionId="presentation-123",
            topic="RAG in enterprise search",
        )

        self.assertEqual(request.session_id, "presentation-123")
        self.assertEqual(request.topic, "RAG in enterprise search")
        self.assertTrue(request.use_web_search)


class PresentationWorkflowServiceTest(unittest.TestCase):
    def test_presentation_workflow_returns_plan_and_manuscript_paths(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            result = service._build_artifact_paths("presentation-123")

        self.assertEqual(result["session_dir"].name, "presentation-123")
        self.assertEqual(result["plan_path"].name, "plan.json")
        self.assertEqual(result["manuscript_path"].name, "manuscript.md")
        self.assertEqual(result["pptx_path"].name, "output.pptx")

    def test_classify_marks_paper_topic_as_academic(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        service = PresentationWorkflowService()
        meta = service._classify_topic("Compare recent RAG papers for enterprise QA")

        self.assertEqual(meta["category"], "academic_technical")
        self.assertTrue(meta["use_academic_research"])
        self.assertTrue(meta["use_web_search"])

    def test_gather_stage_calls_existing_web_search(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        seen = {}

        def fake_web_search(query, **kwargs):
            seen["query"] = query
            return [{"title": "Result", "snippet": "Summary"}]

        service = PresentationWorkflowService()
        service._web_search = fake_web_search

        gathered = service._gather("Enterprise RAG overview", use_web_search=True)

        self.assertEqual(seen["query"], "Enterprise RAG overview")
        self.assertEqual(gathered[0]["title"], "Result")

    def test_plan_stage_returns_slide_outline(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        service = PresentationWorkflowService()
        plan = service._plan(
            topic="Enterprise RAG overview",
            gathered=[{"title": "Enterprise RAG", "snippet": "Key trends"}],
            target_pages=4,
        )

        self.assertTrue(plan["title"])
        self.assertEqual(len(plan["slides"]), 4)
        self.assertIn("title", plan["slides"][0])
        self.assertIn("bullets", plan["slides"][0])

    def test_draft_stage_creates_markdown_pages(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        service = PresentationWorkflowService()
        markdown = service._draft(
            {
                "title": "Enterprise RAG overview",
                "slides": [
                    {"title": "Intro", "bullets": ["A", "B"]},
                    {"title": "Architecture", "bullets": ["C", "D"]},
                ],
            }
        )

        self.assertIn("# Intro", markdown)
        self.assertIn("---", markdown)
        self.assertIn("- A", markdown)

    def test_run_topic_runs_full_workflow_and_returns_artifacts(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            self.assertTrue(result["plan_path"].endswith("plan.json"))
            self.assertTrue(result["manuscript_path"].endswith("manuscript.md"))
            self.assertTrue(result["pptx_path"].endswith("output.pptx"))

            plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["title"], "Enterprise RAG overview")


if __name__ == "__main__":
    unittest.main()
