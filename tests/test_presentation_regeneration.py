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


class PresentationRegenerationTest(unittest.TestCase):
    def test_regenerate_from_saved_artifacts_restores_plan_and_pptx(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        with TemporaryDirectory() as tmp_dir:
            service = PresentationWorkflowService(storage_root=Path(tmp_dir))
            result = service.run_topic("presentation-123", "Enterprise RAG overview")

            plan_path = Path(result["plan_path"])
            original_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_path.write_text(
                json.dumps(
                    {
                        "title": "HACKED",
                        "slides": [{"title": "Injected", "bullets": ["bad"]}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            pptx_path = Path(result["pptx_path"])
            if pptx_path.exists():
                pptx_path.unlink()

            regenerated = service.regenerate_from_artifacts("presentation-123")

            restored_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertNotEqual(restored_plan["title"], "HACKED")
            self.assertEqual(restored_plan["title"], original_plan["title"])
            self.assertTrue(Path(regenerated["pptx_path"]).exists())
            self.assertTrue(Path(regenerated["quality_report_path"]).exists())
            self.assertTrue(regenerated["regenerated_from_artifacts"])
            self.assertEqual(regenerated["answer"], "已基于保存的演示工件重新生成“Enterprise RAG overview”的 PPT。")


if __name__ == "__main__":
    unittest.main()
