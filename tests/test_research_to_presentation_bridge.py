import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

STUB_MODULES = [
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
sys.modules["models.factory"].qwen_model = types.SimpleNamespace(init_model=lambda streaming=False: None)
sys.modules["tools.websearch_tool"].web_search = lambda query, **kwargs: []


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class ResearchToPresentationBridgeTest(unittest.TestCase):
    def test_run_topic_can_use_research_report_as_input(self):
        from agents.presentation_workflow_service import PresentationWorkflowService

        research_root = Path(tempfile.mkdtemp())
        report_dir = research_root / "research_session_abc"
        report_dir.mkdir(parents=True, exist_ok=True)
        final_report = """# LLM Agents Survey

## 核心发现
- Planning benefits from explicit branch synthesis.
- Research artifacts make reruns deterministic.

## 来源概览
- Paper A
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            service = PresentationWorkflowService(storage_root=Path(tmpdir))
            original_research_module = sys.modules.get("agents.research_workflow_service")
            fake_research_module = types.ModuleType("agents.research_workflow_service")
            fake_research_module.research_workflow_service = types.SimpleNamespace(
                reload_research_artifacts=lambda session_id: {
                    "manifest": {
                        "session_id": session_id,
                        "question": "LLM Agents Survey",
                        "report_version": "v2.3",
                        "files": {"final_report": str(report_dir / "final_report.md")},
                    },
                    "final_report": final_report,
                    "paths": {"session_dir": str(report_dir), "final_report": str(report_dir / "final_report.md")},
                }
            )
            sys.modules["agents.research_workflow_service"] = fake_research_module
            try:
                result = service.run_topic(
                    session_id="presentation-123",
                    topic=None,
                    research_session_id="research_session_abc",
                )
            finally:
                if original_research_module is None:
                    sys.modules.pop("agents.research_workflow_service", None)
                else:
                    sys.modules["agents.research_workflow_service"] = original_research_module

            plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
            manuscript = Path(result["manuscript_path"]).read_text(encoding="utf-8")

        self.assertEqual(result["research_session_id"], "research_session_abc")
        self.assertEqual(result["source_report_path"], str(report_dir / "final_report.md"))
        self.assertEqual(plan["title"], "LLM Agents Survey")
        self.assertGreaterEqual(len(plan["slides"]), 2)
        self.assertIn("## 核心发现", manuscript)
        self.assertIn("Planning benefits from explicit branch synthesis.", manuscript)
        self.assertIn("基于研究报告", result["answer"])


if __name__ == "__main__":
    unittest.main()
