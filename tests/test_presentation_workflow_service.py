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

            self.assertTrue(result["artifacts"]["manifest_path"].endswith("artifact_manifest.json"))
            self.assertTrue(result["plan_path"].endswith("plan.json"))
            self.assertTrue(result["manuscript_path"].endswith("manuscript.md"))
            self.assertTrue(result["pptx_path"].endswith("output.pptx"))
            self.assertIn("artifacts", result)
            self.assertIn("download_urls", result["artifacts"])
            self.assertTrue(result["artifacts"]["download_urls"]["pptx"].endswith("/pptx"))
            self.assertTrue(result["artifacts"]["download_urls"]["outline"].endswith("/outline"))
            self.assertTrue(result["artifacts"]["download_urls"]["layout"].endswith("/layout"))
            self.assertTrue(result["artifacts"]["download_urls"]["schema"].endswith("/schema"))
            self.assertTrue(result["artifacts"]["download_urls"]["design"].endswith("/design"))
            self.assertTrue(result["artifacts"]["download_urls"]["quality"].endswith("/quality"))
            self.assertTrue(Path(result["artifacts"]["quality_report_path"]).exists())
            self.assertIn("quality_report", result["artifacts"])

            plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["title"], "Enterprise RAG overview")

    def test_run_topic_includes_saved_user_materials(self):
        from agents.presentation_workflow_service import PresentationWorkflowService
        from services.presentation_material_service import PresentationMaterialService

        with TemporaryDirectory() as presentation_tmp, TemporaryDirectory() as materials_tmp:
            material_service = PresentationMaterialService(storage_root=Path(materials_tmp))
            material_service.save_material_entries(
                "presentation-123",
                [
                    {
                        "source_type": "paste",
                        "material_type": "text",
                        "title": "My outline",
                        "content": "One, two, three",
                    },
                    {
                        "source_type": "link",
                        "material_type": "link",
                        "title": "Reference link",
                        "url": "https://example.com/reference",
                    },
                ],
            )

            service = PresentationWorkflowService(
                storage_root=Path(presentation_tmp),
                material_service=material_service,
            )
            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            self.assertEqual(result["artifacts"]["materials_count"], 2)
            self.assertTrue(result["artifacts"]["materials_path"].endswith("materials.json"))
            self.assertEqual(len(result["artifacts"]["materials"]), 2)
            self.assertIn("用户素材", Path(result["manuscript_path"]).read_text(encoding="utf-8"))
    def test_run_topic_writes_structured_outline_and_filters_noise(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            service._web_search = lambda query: [
                {
                    "title": "Research process",
                    "snippet": "bridge\nplan\ndraft\n{\"debug\": true}\n核心发现",
                }
            ]

            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            outline_path = Path(result["artifacts"]["outline_path"])
            self.assertTrue(outline_path.exists())
            self.assertEqual(outline_path.name, "outline.json")

            outline = json.loads(outline_path.read_text(encoding="utf-8"))
            self.assertEqual(outline["title"], "Enterprise RAG overview")
            self.assertGreaterEqual(len(outline["pages"]), 2)
            first_page = outline["pages"][0]
            self.assertIn("purpose", first_page)
            self.assertIn("topic", first_page)
            self.assertIn("indexes", first_page)
            self.assertIn("images", first_page)
            outline_text = json.dumps(outline, ensure_ascii=False)
            self.assertNotIn("bridge", outline_text)
            self.assertNotIn("{\"debug\": true}", outline_text)

    def test_run_topic_persists_layout_selection(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            service._web_search = lambda query: [
                {"title": "One", "snippet": "Short"},
                {"title": "Two", "snippet": "More text"},
                {"title": "Three", "snippet": "Another item"},
                {"title": "Four", "snippet": "One two three four five six seven"},
            ]

            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            layout_path = Path(result["artifacts"]["layout_path"])
            self.assertTrue(layout_path.exists())
            self.assertEqual(layout_path.name, "layout.json")

            layout = json.loads(layout_path.read_text(encoding="utf-8"))
            layouts = [page["layout"] for page in layout["pages"]]
            self.assertIn("cover", layouts[0])
            self.assertIn("layout_summary", layout)
            self.assertEqual(result["artifacts"]["layout_path"], str(layout_path))
            self.assertIn("layout", result["artifacts"]["layout"]["pages"][0])

    def test_run_topic_persists_schema_generation(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            service._web_search = lambda query: [
                {"title": "One", "snippet": "Short"},
                {"title": "Two", "snippet": "More text"},
                {"title": "Three", "snippet": "Another item"},
            ]

            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            schema_path = Path(result["artifacts"]["schema_path"])
            self.assertTrue(schema_path.exists())
            self.assertEqual(schema_path.name, "schema.json")

            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(schema["title"], "Enterprise RAG overview")
            self.assertEqual(len(schema["pages"]), len(result["artifacts"]["layout"]["pages"]))
            first_elements = schema["pages"][0]["elements"]
            self.assertTrue(first_elements)
            self.assertIn("type", first_elements[0])
            self.assertIn("max_chars", first_elements[0])

    def test_run_topic_persists_design_layer(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            service._web_search = lambda query: [
                {"title": "One", "snippet": "Short"},
                {"title": "Two", "snippet": "More text"},
                {"title": "Three", "snippet": "Another item"},
                {"title": "Four", "snippet": "One two three four five six seven"},
            ]

            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            design_path = Path(result["artifacts"]["design_path"])
            self.assertTrue(design_path.exists())
            self.assertEqual(design_path.name, "design.json")

            design = json.loads(design_path.read_text(encoding="utf-8"))
            self.assertIn("theme", design)
            self.assertEqual(design["theme"]["name"], "academic_research")
            self.assertEqual(result["artifacts"]["design"]["pages"][0]["role"], "hero")
            self.assertEqual(result["artifacts"]["design"]["pages"][-1]["emphasis"], "high")


if __name__ == "__main__":
    unittest.main()
