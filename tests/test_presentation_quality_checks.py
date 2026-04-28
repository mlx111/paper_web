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
    "loguru",
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
sys.modules["tools.websearch_tool"].web_search = lambda query, **kwargs: []


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class PresentationQualityChecksTest(unittest.TestCase):
    def test_quality_check_passes_for_freshly_generated_presentation(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            service.run_topic("presentation-123", "Enterprise RAG overview")

            quality = service.check_quality("presentation-123")

            self.assertTrue(quality["passed"])
            self.assertTrue(Path(quality["quality_report_path"]).exists())
            self.assertEqual(quality["summary"]["pptx_exists"], True)

    def test_quality_check_flags_placeholder_text_in_plan(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            plan_path = Path(result["plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["slides"][0]["bullets"].append("bridge debug placeholder")
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

            quality = service.check_quality("presentation-123")

            self.assertFalse(quality["passed"])
            self.assertTrue(any("Placeholder or debug text" in issue for issue in quality["issues"]))


if __name__ == "__main__":
    unittest.main()
