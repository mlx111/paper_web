import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

STUB_MODULES = ["loguru"]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in STUB_MODULES}

for name in STUB_MODULES:
    sys.modules.setdefault(name, types.ModuleType(name))

sys.modules["loguru"].logger = types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)


def tearDownModule():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class PresentationDesignServiceTest(unittest.TestCase):
    def test_build_design_assigns_theme_and_roles(self):
        from services.presentation_design_service import PresentationDesignService

        service = PresentationDesignService()
        schema = {
            "title": "Enterprise RAG overview",
            "source": "research_report",
            "pages": [
                {
                    "page_index": 1,
                    "purpose": "封面与概览",
                    "topic": "Enterprise RAG overview",
                    "layout": "cover",
                    "elements": [{"type": "title", "text": "Enterprise RAG overview", "max_chars": 42}],
                },
                {
                    "page_index": 2,
                    "purpose": "背景与问题",
                    "topic": "Enterprise RAG overview",
                    "layout": "single_column_text",
                    "elements": [{"type": "bullet", "text": "Long content", "max_chars": 80}],
                },
                {
                    "page_index": 3,
                    "purpose": "总结与展望",
                    "topic": "Enterprise RAG overview",
                    "layout": "closing",
                    "elements": [{"type": "bullet", "text": "Final point", "max_chars": 80}],
                },
            ],
        }

        design = service.build_design(schema)

        self.assertEqual(design["theme"]["name"], "academic_research")
        self.assertIn("palette", design["theme"])
        self.assertEqual(design["pages"][0]["role"], "hero")
        self.assertEqual(design["pages"][1]["role"], "content")
        self.assertEqual(design["pages"][2]["role"], "closing")
        self.assertEqual(design["pages"][2]["emphasis"], "high")
        self.assertIn("font", design["theme"])

    def test_apply_design_attaches_page_metadata(self):
        from services.presentation_design_service import PresentationDesignService

        service = PresentationDesignService()
        schema = {
            "title": "Enterprise RAG overview",
            "source": "general",
            "pages": [
                {
                    "page_index": 1,
                    "purpose": "封面与概览",
                    "topic": "Enterprise RAG overview",
                    "layout": "cover",
                    "elements": [{"type": "title", "text": "Enterprise RAG overview", "max_chars": 42}],
                }
            ],
        }

        designed = service.apply_design(schema, service.build_design(schema))

        self.assertIn("design", designed)
        self.assertIn("design", designed["pages"][0])
        self.assertEqual(designed["pages"][0]["design"]["role"], "hero")
        self.assertIn("accent", designed["pages"][0]["design"])


if __name__ == "__main__":
    unittest.main()
